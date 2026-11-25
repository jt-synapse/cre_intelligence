import { expect, test, type Page } from "@playwright/test";

const generation = "325c2674-81f9-488b-a029-c05f46336a13";
const feature = (id: string, x: number) => ({
  type: "Feature",
  id,
  properties: {
    reader_version: generation,
    projection_generation_id: generation,
    county_fips: "99001",
    primary_pin: "PIN-" + id,
    address: id + " Test Road",
  },
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [x, 33.9],
        [x + 0.001, 33.9],
        [x + 0.001, 33.901],
        [x, 33.901],
        [x, 33.9],
      ],
    ],
  },
});
const parcels = {
  type: "FeatureCollection",
  features: [feature("west", -84.001), feature("east", -84)],
};

async function openMap(page: Page, imageryStyle: string | null = null) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/config", (route) =>
    route.fulfill({ json: { demo: true, basemap: imageryStyle } }),
  );
  await page.route("**/unavailable-style", (route) =>
    route.fulfill({ status: 503 }),
  );
  await page.route("**/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/v1/me")
      return route.fulfill({
        json: {
          subject: "field-user",
          organizations: [
            { id: "test-org", name: "Field team", role: "analyst" },
          ],
        },
      });
    if (url.pathname === "/v1/field/places")
      return route.fulfill({ json: { folders: [], pins: [] } });
    if (url.pathname.startsWith("/v1/tiles/"))
      return route.fulfill({
        contentType: "application/vnd.mapbox-vector-tile",
        body: Buffer.alloc(0),
      });
    if (url.pathname === "/v1/parcels") return route.fulfill({ json: parcels });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open local demo" }).click();
  await expect(
    page.getByRole("button", { name: "Locate me", exact: true }),
  ).toBeVisible();
}

test("GPS is opt-in and denied access leaves address and parcel search available", async ({
  page,
}) => {
  await page.addInitScript(() => {
    let gpsCalls = 0;
    Object.defineProperty(window, "gpsCalls", { get: () => gpsCalls });
    Object.defineProperty(navigator, "geolocation", {
      value: {
        getCurrentPosition(
          _success: unknown,
          denied: (error: { code: number }) => void,
        ) {
          gpsCalls++;
          denied({ code: 1 });
        },
      },
    });
  });
  await openMap(page);
  expect(await page.evaluate(() => Reflect.get(window, "gpsCalls"))).toBe(0);
  await page.getByRole("button", { name: "Locate me", exact: true }).click();
  await expect(page.getByText(/location permission was denied/i)).toBeVisible();
  await expect(page.getByRole("searchbox")).toBeEnabled();
  await expect(
    page.getByRole("button", { name: /west Test Road/i }),
  ).toBeEnabled();
});

test("a follow fix finds nearby parcels and a manual pan stops following", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      value: {
        watchPosition(success: PositionCallback) {
          setTimeout(
            () =>
              success({
                coords: { longitude: -84, latitude: 33.9, accuracy: 17 },
              } as GeolocationPosition),
            0,
          );
          return 5;
        },
        clearWatch(id: number) {
          document.documentElement.dataset.clearedWatch = String(id);
        },
      },
    });
  });
  await openMap(page);
  const nearby = page.waitForRequest((req) =>
    new URL(req.url()).searchParams.has("bbox"),
  );
  await page.getByRole("button", { name: "Follow location" }).click();
  const bounds = new URL((await nearby).url()).searchParams
    .get("bbox")!
    .split(",")
    .map(Number);
  expect(bounds[0]).toBeLessThan(-84);
  expect(bounds[2]).toBeGreaterThan(-84);
  await expect(page.getByText(/accuracy.*17 m/i)).toBeVisible();
  const canvas = page.locator("canvas.maplibregl-canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  const x = box.x + box.width / 2,
    y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 70, y, { steps: 5 });
  await page.mouse.up();
  await expect(page.locator("html")).toHaveAttribute("data-cleared-watch", "5");
  await expect(
    page.getByRole("button", { name: "Follow location" }),
  ).toBeEnabled();
});

test("failed imagery leaves parcel choices and user-drawn distance available", async ({
  page,
}) => {
  await openMap(page, "/unavailable-style");
  await expect(page.getByText(/imagery unavailable/i)).toBeVisible();
  const canvas = page.locator("canvas.maplibregl-canvas");
  await expect(
    page.getByRole("button", { name: "Search this area" }),
  ).toBeEnabled();
  await expect(async () => {
    await canvas.click();
    await expect(
      page.getByRole("group", { name: "Choose a parcel" }),
    ).toBeVisible({ timeout: 800 });
  }).toPass();
  await page.getByRole("button", { name: "Measure", exact: true }).click();
  await canvas.click({ position: { x: 95, y: 100 } });
  await canvas.click({ position: { x: 170, y: 125 } });
  await expect(page.getByText(/Estimated distance.*[1-9].*ft/i)).toBeVisible();
  await page.getByRole("button", { name: "Area", exact: true }).click();
  await canvas.click({ position: { x: 95, y: 100 } });
  await canvas.click({ position: { x: 170, y: 125 } });
  await canvas.click({ position: { x: 110, y: 160 } });
  await expect(page.getByText(/Estimated area.*acres/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo point" })).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("workspace credentials stay on parcel tile requests when imagery is configured", async ({
  page,
}) => {
  const providerHeaders: Record<string, string>[] = [],
    tileHeaders: Record<string, string>[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/tiles/"))
      tileHeaders.push(request.headers());
    if (url.hostname === "imagery.example.invalid")
      providerHeaders.push(request.headers());
  });
  await page.route("**/imagery-style", (route) =>
    route.fulfill({
      json: {
        version: 8,
        sources: {
          air: {
            type: "raster",
            tiles: ["https://imagery.example.invalid/{z}/{x}/{y}"],
            tileSize: 256,
            attribution: "Example imagery",
          },
        },
        layers: [{ id: "air", type: "raster", source: "air" }],
      },
    }),
  );
  await page.route("https://imagery.example.invalid/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      headers: { "access-control-allow-origin": "*" },
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPYfebufwAIDgNkDUWIVwAAAABJRU5ErkJggg==",
        "base64",
      ),
    }),
  );
  await openMap(page, "/imagery-style");
  await expect.poll(() => tileHeaders.length).toBeGreaterThan(0);
  await expect.poll(() => providerHeaders.length).toBeGreaterThan(0);
  expect(
    tileHeaders.every(
      (h) =>
        h.authorization === "Bearer local-demo" &&
        h["x-organization-id"] === "test-org",
    ),
  ).toBe(true);
  expect(
    providerHeaders.every((h) => !h.authorization && !h["x-organization-id"]),
  ).toBe(true);
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(
    page.getByRole("button", { name: "Search this area" }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
