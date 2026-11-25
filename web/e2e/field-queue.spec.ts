import { expect, test } from "@playwright/test";

test("a same-workspace actor switch invalidates old tabs and erases pending field data", async ({
  page,
}) => {
  await page.goto("/field-offline");
  const result = await page.evaluate(async (modulePath) => {
    const q = await import(modulePath);
    const a = await q.bindSession("org", "actor-a", true);
    await q.enqueue(a, "parcel", "actor A note", null);
    const before = (await q.pending(a)).length;
    const b = await q.bindSession("org", "actor-b", true);
    const denied = await q.pending(a).then(
      () => false,
      () => true,
    );
    const after = (await q.pending(b)).length;
    await q.enqueue(b, "parcel", "actor B note", null);
    await q.clearSession();
    return [
      before,
      denied,
      after,
      await q.pending(b).then(
        () => false,
        () => true,
      ),
    ];
  }, "/field-store.js");
  expect(result).toEqual([1, true, 0, true]);
});

test("queue saturation and expiry preserve acknowledged local writes", async ({
  page,
}) => {
  await page.goto("/field-offline");
  const result = await page.evaluate(async (modulePath) => {
    const q = await import(modulePath);
    const grant = await q.bindSession("org", "actor", true);
    let accepted = 0;
    for (let i = 0; i < 100; i++) {
      try {
        await q.enqueue(grant, "parcel", "note " + i, null);
        accepted++;
      } catch {
        break;
      }
    }
    const rows = await q.pending(grant);
    const expired = { ...grant, expires: Date.now() - 1 };
    const denied = await q.pending(expired).then(
      () => false,
      () => true,
    );
    return [accepted > 0 && accepted < 100, rows.length === accepted, denied];
  }, "/field-store.js");
  expect(result).toEqual([true, true, true]);
});

test("unauthorized field writes stay blocked after grant expiry or workspace revocation", async ({
  page,
}) => {
  await page.goto("/field-offline");
  const result = await page.evaluate(async (modulePath) => {
    const q = await import(modulePath);
    const writer = await q.bindSession("org", "writer", true);
    const expiryHours = Math.round((writer.expires - Date.now()) / 3_600_000);
    const denied = (f: Promise<unknown>) =>
      f.then(
        () => false,
        () => true,
      );
    const expiredWrite = await denied(
      q.enqueue({ ...writer, expires: Date.now() - 1 }, "p", "expired", null),
    );
    const actorWrite = await denied(
      q.enqueue(
        { ...writer, subject: "another" },
        "p",
        "different actor",
        null,
      ),
    );
    await q.suspendSession(writer);
    const revokedWrite = await denied(q.enqueue(writer, "p", "revoked", null));
    const viewer = await q.bindSession("org", "writer", false);
    const viewerWrite = await denied(q.enqueue(viewer, "p", "read only", null));
    const oldRenewal = await denied(q.renewSession(writer));
    const smallest = await q.bindSession("org", "writer", true, -2);
    const largest = await q.bindSession("org", "writer", true, 24);
    return [
      Math.round((smallest.expires - Date.now()) / 3_600_000),
      Math.round((largest.expires - Date.now()) / 3_600_000),
      expiryHours,
      expiredWrite,
      actorWrite,
      revokedWrite,
      viewerWrite,
      oldRenewal,
    ];
  }, "/field-store.js");
  expect(result).toEqual([1, 12, 12, true, true, true, true, true]);
});
