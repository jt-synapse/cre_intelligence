import test from "node:test";
import assert from "node:assert/strict";
import { pathMeters, areaMeters, accuracyRing } from "../lib/map-geometry.ts";

test("drawn paths and areas use ground distance and handle winding", () => {
  const path = [
    [0, 0],
    [0.001, 0],
    [0.001, 0.001],
    [0, 0.001],
  ];
  assert.ok(Math.abs(pathMeters(path) - 333.585) < 0.1);
  assert.ok(Math.abs(areaMeters(path) - 12364.35) < 1);
  assert.ok(Math.abs(areaMeters(path.toReversed()) - areaMeters(path)) < 0.1);
  assert.equal(areaMeters(path.slice(0, 2)), 0);
});

test("GPS radius remains in meters across latitude", () => {
  const center = [-84.01, 33.95];
  const ring = accuracyRing(center, 28);
  assert.deepEqual(ring[0], ring.at(-1));
  for (const vertex of ring)
    assert.ok(Math.abs(pathMeters([center, vertex]) - 28) < 0.02);
});

test("crossing a drawn outline cannot produce a trusted acreage", () => {
  assert.equal(
    areaMeters([
      [0, 0],
      [0.003, 0.002],
      [0.003, 0],
      [0, 0.001],
    ]),
    null,
  );
});
