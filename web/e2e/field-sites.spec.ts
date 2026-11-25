import { expect, test } from "@playwright/test";

for (const device of [
  { name: "phone", width: 390, height: 844, parcels: 3 },
  { name: "tablet", width: 820, height: 1180, parcels: 6 },
]) {
  test(`${device.name} saves, reopens, and revises a ${device.parcels}-parcel site`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto("/");
    await page.getByRole("button", { name: "Open local demo" }).click();
    const section = page.getByRole("region", {
      name: "Field sites",
      exact: true,
    });
    const members = section
      .getByRole("list", { name: "Site members" })
      .getByRole("listitem");
    await section.getByLabel("Add map selections to site").check();
    for (let i = 0; i < device.parcels; i++) {
      await page
        .getByRole("button", {
          name: new RegExp(100 + i + " Example Commerce Dr"),
        })
        .first()
        .click();
      await expect(members).toHaveCount(i + 1);
    }
    await section.getByLabel("Add map selections to site").uncheck();
    await section
      .getByRole("button", { name: "Preview site", exact: true })
      .click();
    await expect(
      section.getByText("Measured union", { exact: false }),
    ).toBeVisible();
    if (device.parcels === 3) {
      await expect(
        section.getByText("3 separate polygon components"),
      ).toBeVisible();
    } else {
      await expect(
        section.getByText(/separate polygon components/),
      ).toHaveCount(0);
    }
    const name = `Field visit ${device.name} ${Date.now()}`;
    await section.getByLabel("Site name").fill(name);
    await section
      .getByRole("button", { name: "Save site", exact: true })
      .click();
    await expect(section.getByRole("status")).toHaveText("Site saved.");
    await page.reload();
    await section
      .getByLabel("Saved sites")
      .selectOption({ label: name + " · revision 1" });
    await expect(members).toHaveCount(device.parcels);
    await expect(
      section.getByText("Measured union", { exact: false }),
    ).toBeVisible();

    // Hold an actual server response while the user removes a member.
    let release!: () => void;
    const held = new Promise<void>((done) => {
      release = done;
    });
    let received!: () => void;
    const requested = new Promise<void>((done) => {
      received = done;
    });
    await page.route(
      "**/v1/field/sites/preview",
      async (route) => {
        const response = await route.fetch();
        received();
        await held;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    await section
      .getByRole("button", { name: "Preview site", exact: true })
      .click();
    await requested;
    await section
      .getByRole("button", { name: /^Remove / })
      .last()
      .click();
    const oldResponse = page.waitForResponse((response) =>
      response.url().endsWith("/v1/field/sites/preview"),
    );
    release();
    await oldResponse;
    await expect(
      section.getByRole("button", { name: "Save site revision" }),
    ).toBeDisabled();
    await expect(
      section.getByText("Measured union", { exact: false }),
    ).toHaveCount(0);
    await section
      .getByRole("button", { name: "Preview site", exact: true })
      .click();
    await section.getByRole("button", { name: "Save site revision" }).click();
    await expect(section.getByRole("status")).toHaveText("Site saved.");
    await section
      .getByRole("button", { name: "Reopen latest revision" })
      .click();
    await expect(members).toHaveCount(device.parcels - 1);
  });
}
