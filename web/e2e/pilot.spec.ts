import { test, expect } from "@playwright/test";

test("save a synthetic parcel, investigate it, and export a reviewed financial dossier", async ({
  page,
}) => {
  const suffix = Date.now();
  const errs: string[] = [];
  page.on("pageerror", (error) => errs.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await expect(
    page.getByRole("heading", { name: "Parcel explorer" }),
  ).toBeVisible();
  await page.getByRole("searchbox").fill("100 Example Commerce");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page
    .getByRole("button", { name: /100 Example Commerce Dr/i })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Source evidence" }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: /Save (as provisional property|property to workspace)/,
    })
    .click();
  await page
    .getByRole("button", { name: "Saved properties", exact: true })
    .click();
  await page
    .getByRole("button", { name: /100 Example Commerce Dr/i })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Source evidence" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Investigations", exact: true })
    .click();
  await page.getByText("Start an investigation", { exact: true }).click();
  await page
    .getByLabel("Research objective")
    .fill("Test opaque ownership " + suffix);
  await page
    .getByRole("button", { name: "Start investigation", exact: true })
    .click();
  await expect(page.getByText("unresolved", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await page
    .getByRole("button", { name: "Opportunities", exact: true })
    .click();
  await page.getByText("Add an opportunity", { exact: true }).click();
  await page.getByLabel("Opportunity title").fill("Test prospect " + suffix);
  await page
    .getByRole("button", { name: "Create opportunity", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Test prospect " + suffix }),
  ).toBeVisible();
  await page.getByText("Log an activity or task", { exact: true }).click();
  await page.getByLabel("Activity details").fill("Review parcel evidence");
  await page.getByRole("button", { name: "Add activity", exact: true }).click();
  await expect(
    page.getByText("Review parcel evidence", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Financials", exact: true }).click();
  await page.getByText("Create a financial scenario", { exact: true }).click();
  await page.getByLabel("Scenario name").fill("Test model " + suffix);
  await page.getByLabel("Annual effective gross income").fill("120000");
  await page.getByLabel("Annual operating expenses").fill("20000");
  await page
    .getByLabel("Input source or reference")
    .fill("Synthetic browser fixture");
  await page
    .getByRole("button", { name: "Calculate and save", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Test model " + suffix }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell").filter({ hasText: "100000.00" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByText("Prepare a dossier", { exact: true }).click();
  const scenarioSelect = page.locator('select[name="scenario_id"]');
  const option = scenarioSelect
    .locator("option")
    .filter({ hasText: "Test model " + suffix });
  await expect(option).toHaveCount(1);
  await scenarioSelect.selectOption((await option.getAttribute("value")) || "");
  await page
    .getByRole("button", { name: "Prepare report for review", exact: true })
    .click();
  await page.getByText("Review report for export", { exact: true }).click();
  await page
    .getByLabel("Review notes")
    .fill("Reviewed synthetic scenario inputs.");
  await page
    .getByRole("button", { name: "Submit report review", exact: true })
    .click();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download reviewed PDF", exact: true })
    .click({ timeout: 20000 });
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
  expect(errs).toEqual([]);
});
