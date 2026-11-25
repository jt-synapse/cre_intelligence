import { expect, test } from "@playwright/test";

test("select a mapped parcel and verify the identity, representative role, and professional channel", async ({
  page,
}) => {
  const suffix = Date.now();
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await page.getByRole("searchbox").fill("100 Example Commerce");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /100 Example Commerce Dr/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Search this area" }),
  ).toBeEnabled();
  await expect(async () => {
    await page.locator("canvas.maplibregl-canvas").click();
    await expect(
      page.getByRole("heading", { name: "Source evidence" }),
    ).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 8000 });
  await page
    .getByRole("button", {
      name: /Save (as provisional property|property to workspace)/,
    })
    .click();
  await page
    .getByRole("button", { name: "Investigations", exact: true })
    .click();
  await page.getByText("Start an investigation", { exact: true }).click();
  await page
    .getByLabel("Research objective")
    .fill("Test representative " + suffix);
  await page
    .getByRole("button", { name: "Start investigation", exact: true })
    .click();
  await expect(page.getByText("unresolved", { exact: true })).toBeVisible();
  const principal = "Sample representative " + suffix;
  async function record(kind: string, assertion: string) {
    const editor = page
      .locator("details")
      .filter({
        has: page.getByText("Record source evidence", { exact: true }),
      })
      .last();
    if (!((await editor.getAttribute("open")) !== null))
      await editor.locator("summary").first().click();
    const form = editor.locator("form").first();
    await form.locator('[name="kind"]').selectOption(kind);
    await form.locator('[name="subject"]').fill(principal);
    await form.locator('[name="assertion"]').fill(assertion);
    await form
      .locator('[name="reference"]')
      .fill("Synthetic registry fixture " + suffix);
    await form.locator('[name="locator"]').fill("Page 1");
    await form
      .locator('[name="source_excerpt"]')
      .fill("The synthetic record states: " + assertion);
    if (kind !== "entity_identity") {
      const identity = form
        .locator('[name="identity_finding_id"] option')
        .filter({ hasText: principal });
      await expect(identity).toHaveCount(1);
      await form
        .locator('[name="identity_finding_id"]')
        .selectOption((await identity.getAttribute("value")) || "");
    }
    if (kind === "property_role")
      await form.locator('[name="relationship"]').selectOption("asset_manager");
    if (kind === "business_channel") {
      await form
        .locator('[name="channel_kind"]')
        .selectOption("business_email");
      await form
        .locator('[name="channel_value"]')
        .fill("research-" + suffix + "@example.org");
    }
    await form.getByRole("button", { name: "Submit evidence" }).click();
    const finding = page
      .locator("article.finding")
      .filter({ has: page.getByText(assertion, { exact: true }) });
    await expect(finding).toBeVisible();
    await finding.getByText("Review finding", { exact: true }).click();
    await finding
      .getByLabel("Review reason")
      .fill("Compared with the named source page.");
    await finding.getByRole("button", { name: "Record decision" }).click();
    await expect(finding.locator(".meta")).toContainText("verified");
  }
  await record("entity_identity", "Registered business identity " + suffix);
  await record("property_role", "Documented asset manager " + suffix);
  await record("business_channel", "Published professional email " + suffix);
  await expect(
    page.getByText("verified business contact", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Documented relationships" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Record", exact: true }),
  ).toBeVisible();
  await expect(() =>
    page.evaluate(() => {
      if (document.documentElement.scrollWidth <= innerWidth) return;
      const overflow = Array.from(document.querySelectorAll("body *"))
        .filter((el) => el.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 8)
        .map(
          (el) =>
            el.tagName +
            "." +
            el.className +
            "[" +
            el.getAttribute("name") +
            "]@" +
            Math.round(el.getBoundingClientRect().right),
        );
      throw new Error("Horizontal overflow: " + overflow.join(", "));
    }),
  ).toPass({ timeout: 2000 });
});
