import { expect, test, type Page } from "@playwright/test";

async function selectParcel(page: Page) {
  await page.getByRole("searchbox").fill("100 Example Commerce");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page
    .getByRole("button", { name: /100 Example Commerce Dr/i })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Save field capture" }),
  ).toBeEnabled();
}

test("offline phone capture survives reload and a lost success response without duplication", async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await selectParcel(page);
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
  const note = "Loading bay " + Date.now();
  // Use the browser image encoder to send a real camera-compatible photo.
  const bytes = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 3;
    return canvas.toDataURL("image/png").split(",")[1];
  });
  await context.setOffline(true);
  await page.getByLabel("Field note").fill(note);
  await page.getByLabel("Field photo").setInputFiles({
    name: "loading-bay.png",
    mimeType: "image/png",
    buffer: Buffer.from(bytes, "base64"),
  });
  await page.getByRole("button", { name: "Save field capture" }).click();
  await expect(page.getByText("Pending sync · Photo attached")).toBeVisible();
  const discardPrompt = page.waitForEvent("dialog");
  const signOut = page.getByRole("button", { name: "Sign out" }).click();
  const confirmation = await discardPrompt;
  expect(confirmation.message()).toContain("1 pending");
  await confirmation.dismiss();
  await signOut;
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Offline fieldwork" }),
  ).toBeVisible();
  await expect(
    page.getByRole("listitem").filter({ hasText: note }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Pending field photo" }),
  ).toBeVisible();
  const cached = await page.evaluate(async () => {
    const paths: string[] = [];
    for (const name of await caches.keys()) {
      for (const req of await (await caches.open(name)).keys())
        paths.push(new URL(req.url).pathname);
    }
    return paths.sort();
  });
  expect(cached).toEqual(["/field-offline", "/field-store.js"]);
  let dropped = false;
  await page.route("**/v1/parcels/*/field-captures", async (route) => {
    if (route.request().method() === "POST" && !dropped) {
      const committed = await route.fetch();
      expect(committed.ok()).toBe(true);
      dropped = true;
      await route.abort("failed");
    } else await route.continue();
  });
  await context.setOffline(false);
  await expect(
    page.getByRole("heading", { name: "Parcel explorer" }),
  ).toBeVisible();
  await selectParcel(page);
  await expect.poll(() => dropped).toBe(true);
  const record = page
    .locator("article.finding")
    .filter({ has: page.getByText(note, { exact: true }) });
  await expect(record).toHaveCount(1, { timeout: 15000 });
  await expect(
    record.getByRole("button", { name: "View photo" }),
  ).toBeVisible();
  await record.getByRole("button", { name: "View photo" }).click();
  await expect(
    record.getByRole("img", { name: "Saved field photo" }),
  ).toBeVisible();
  await expect(page.getByText("Pending sync · Photo attached")).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("button", { name: "Open local demo" }),
  ).toBeVisible();
  await page.goto("/field-offline");
  await expect(page.getByRole("status")).toContainText("Reconnect and sign in");
  await expect(page.getByText(note, { exact: true })).toHaveCount(0);
});

test("an unavailable IndexedDB still permits workspace sign-in and sign-out", async ({
  page,
}) => {
  await page.addInitScript(() => {
    IDBFactory.prototype.open = () => {
      throw new DOMException("Storage disabled", "SecurityError");
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await expect(
    page.getByRole("heading", { name: "Parcel explorer" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("button", { name: "Open local demo" }),
  ).toBeVisible();
});

test("reconnection rechecks the current role before sending a pending note", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await selectParcel(page);
  await context.setOffline(true);
  await page.getByLabel("Field note").fill("Role changed while offline");
  await page.getByRole("button", { name: "Save field capture" }).click();
  await expect(page.getByText("Pending sync", { exact: true })).toBeVisible();
  let writes = 0;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/field-captures"))
      writes++;
  });
  await page.route("**/v1/me", async (route) => {
    const original = await route.fetch();
    const data = await original.json();
    data.organizations = data.organizations.map((o: object) => ({
      ...o,
      role: "viewer",
    }));
    await route.fulfill({ json: data });
  });
  await context.setOffline(false);
  await expect(
    page.getByRole("button", { name: "Save field capture" }),
  ).toBeDisabled();
  await expect(page.getByText("Role changed while offline")).toHaveCount(0);
  expect(writes).toBe(0);
});

test("a rejected photo allows a later capture to sync and can be retried or discarded from the workspace", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await selectParcel(page);
  await context.setOffline(true);
  const suffix = Date.now();
  const bad = "Damaged photo " + suffix,
    good = "Second visit " + suffix;
  await page.getByLabel("Field note").fill(bad);
  await page.getByLabel("Field photo").setInputFiles({
    name: "broken.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("broken"),
  });
  await page.getByRole("button", { name: "Save field capture" }).click();
  await expect(page.getByText("Pending sync · Photo attached")).toBeVisible();
  await page.getByLabel("Field note").fill(good);
  await page.getByRole("button", { name: "Save field capture" }).click();
  await expect(page.getByText("Pending sync", { exact: true })).toBeVisible();
  await context.setOffline(false);
  const issue = page.getByRole("region", {
    name: "Captures needing attention",
  });
  await expect(issue.getByText(bad, { exact: true })).toBeVisible();
  const saved = page.locator("article.finding").filter({ hasText: good });
  await expect(saved).toHaveCount(1);
  await expect(saved).not.toContainText("Pending sync");
  await expect(page.getByText("Pending sync", { exact: true })).toHaveCount(0);
  await page
    .getByRole("button", { name: "Saved properties", exact: true })
    .click();
  const retry = page.waitForResponse(
    (r) => r.url().endsWith("/field-captures") && r.status() === 422,
  );
  await issue.getByRole("button", { name: "Retry capture" }).click();
  await retry;
  page.once("dialog", (dialog) => dialog.accept());
  await issue.getByRole("button", { name: "Discard capture" }).click();
  await expect(issue).toHaveCount(0);
});
