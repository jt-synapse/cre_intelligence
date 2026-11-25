export type Point = [number, number];
const earthRadius = 6371008.8;
const rad = Math.PI / 180;

export function pathMeters(points: Point[]) {
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const [lon1, lat1] = points[i - 1],
      [lon2, lat2] = points[i];
    const h =
      Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
      Math.cos(lat1 * rad) *
        Math.cos(lat2 * rad) *
        Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
    total += 2 * earthRadius * Math.asin(Math.sqrt(Math.min(1, h)));
  }
  return total;
}

function orientation(a: Point, b: Point, c: Point) {
  return Math.sign(
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
  );
}

function crosses(a: Point, b: Point, c: Point, d: Point) {
  for (const axis of [0, 1]) {
    if (
      Math.max(a[axis], b[axis]) < Math.min(c[axis], d[axis]) ||
      Math.max(c[axis], d[axis]) < Math.min(a[axis], b[axis])
    )
      return false;
  }
  return (
    orientation(a, b, c) * orientation(a, b, d) <= 0 &&
    orientation(c, d, a) * orientation(c, d, b) <= 0
  );
}

// Spherical area of a simple, unclosed ring, using shortest longitude differences.
export function areaMeters(points: Point[]) {
  if (points.length < 3) return 0;
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 2; j < points.length; j++) {
      if (i === 0 && j === points.length - 1) continue;
      if (
        crosses(
          points[i],
          points[i + 1],
          points[j],
          points[(j + 1) % points.length],
        )
      )
        return null;
    }
  }
  let sum = 0;
  points.forEach(([lon, lat], i) => {
    const [nextLon, nextLat] = points[(i + 1) % points.length];
    const delta = ((nextLon - lon + 540) % 360) - 180;
    sum += delta * rad * (Math.sin(lat * rad) + Math.sin(nextLat * rad));
  });
  return (Math.abs(sum) * earthRadius ** 2) / 2;
}

export function accuracyRing([lon, lat]: Point, meters: number): Point[] {
  const distance = meters / earthRadius,
    phi = lat * rad;
  const ring: Point[] = [];
  for (let i = 0; i < 64; i++) {
    const bearing = (2 * Math.PI * i) / 64;
    const nextLat = Math.asin(
      Math.sin(phi) * Math.cos(distance) +
        Math.cos(phi) * Math.sin(distance) * Math.cos(bearing),
    );
    const deltaLon = Math.atan2(
      Math.sin(bearing) * Math.sin(distance) * Math.cos(phi),
      Math.cos(distance) - Math.sin(phi) * Math.sin(nextLat),
    );
    ring.push([lon + deltaLon / rad, nextLat / rad]);
  }
  return [...ring, ring[0]];
}

export function nearbyBounds(point: Point, accuracy: number) {
  const ring = accuracyRing(point, Math.max(250, Math.min(accuracy, 2000)));
  const xs = ring.map(([x]) => x),
    ys = ring.map(([, y]) => y);
  return [
    Math.max(-180, Math.min(...xs)),
    Math.min(...ys),
    Math.min(180, Math.max(...xs)),
    Math.max(...ys),
  ]
    .map((v) => v.toFixed(6))
    .join(",");
}
