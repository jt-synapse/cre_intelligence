import { expect, test } from "@playwright/test";

test("a phone revisits a labeled parcel pin and records an online visit", async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  const places = page.getByRole("region", { name: "Saved field places" });
  const folder = "Survey " + Date.now();
  const label = "Inspect frontage " + Date.now();
  await places.getByText("Create field folder", { exact: true }).click();
  await places.getByLabel("Folder name").fill(folder);
  await places.getByLabel("Folder color").selectOption("violet");
  await places
    .getByRole("button", { name: "Create folder", exact: true })
    .click();
  await expect(
    places.getByText(folder + " folder ready.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /102 Example Commerce Dr/ })
    .first()
    .click();
  await places.getByText(/^(Pin selected parcel|Edit parcel pin)$/).click();
  await places.getByLabel("Pin label").fill(label);
  await places
    .getByLabel("Pin folder")
    .selectOption({ label: folder + " · violet" });
  await places.getByRole("button", { name: "Save pin", exact: true }).click();
  await expect(
    places.getByRole("button", { name: new RegExp(label) }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /101 Example Commerce Dr/ })
    .first()
    .click();
  await expect(
    places.getByRole("heading", { name: "0002 A 001" }),
  ).toBeVisible();
  await places.getByRole("button", { name: new RegExp(label) }).click();
  await expect(
    places.getByRole("heading", { name: "0003 A 001" }),
  ).toBeVisible();
  await places.getByRole("button", { name: "Record visit now" }).click();
  await expect(
    places.getByText("Visit recorded.", { exact: true }),
  ).toBeVisible();
  await expect(
    places.getByRole("button", { name: new RegExp(label + ".*Visited") }),
  ).toBeVisible();
  await context.setOffline(true);
  await expect(
    places.getByText("Connect to view folders and pins or record a visit."),
  ).toBeVisible();
  await expect(
    places.getByRole("button", { name: new RegExp(label) }),
  ).toHaveCount(0);
  await context.setOffline(false);
  await expect(
    places.getByRole("button", { name: new RegExp(label) }),
  ).toBeVisible();
  await page.reload();
  await places
    .getByLabel("Saved pins")
    .selectOption({ label: folder + " · violet" });
  await expect(
    places.getByRole("button", { name: new RegExp(label + ".*Visited") }),
  ).toBeVisible();
});
