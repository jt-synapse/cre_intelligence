import type { FeatureCollection } from "geojson";
import type { Map as LibreMap } from "maplibre-gl";
import { emptyParcels, type Parcels } from "../lib/types";
import { accuracyRing, type Point } from "../lib/map-geometry";
import type { LocationFix } from "./useFieldLocation";

export const emptyGraphics: FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
export type MeasureMode = "distance" | "area" | null;

export function addMapLayers(map: LibreMap) {
  map.addSource("cre-parcels", { type: "geojson", data: emptyParcels });
  map.addLayer({
    id: "cre-fill",
    type: "fill",
    source: "cre-parcels",
    paint: {
      "fill-color": [
        "case",
        ["==", ["get", "selected"], true],
        "#e59431",
        "#368578",
      ],
      "fill-opacity": 0.42,
    },
  });
  map.addLayer({
    id: "cre-boundary",
    type: "line",
    source: "cre-parcels",
    paint: { "line-color": "#205e55", "line-width": 1.7 },
  });
  map.addSource("cre-related", { type: "geojson", data: emptyGraphics });
  map.addLayer({
    id: "cre-related-outline",
    type: "line",
    source: "cre-related",
    paint: { "line-color": "#2866a8", "line-width": 2.5 },
  });
  map.addSource("cre-site", { type: "geojson", data: emptyGraphics });
  map.addLayer({
    id: "cre-site-outline",
    type: "line",
    source: "cre-site",
    paint: {
      "line-color": "#672297",
      "line-width": 4,
      "line-dasharray": [2, 1.4],
    },
  });
  map.addSource("cre-pins", { type: "geojson", data: emptyGraphics });
  map.addLayer({
    id: "cre-saved-pins",
    type: "circle",
    source: "cre-pins",
    paint: {
      "circle-radius": 7,
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
      "circle-color": ["to-color", ["get", "color"], "#236856"],
    },
  });
  map.addSource("cre-location", { type: "geojson", data: emptyGraphics });
  map.addLayer({
    id: "cre-accuracy",
    type: "fill",
    source: "cre-location",
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: {
      "fill-color": "#437ac9",
      "fill-opacity": 0.18,
      "fill-outline-color": "#20539a",
    },
  });
  map.addLayer({
    id: "cre-fix",
    type: "circle",
    source: "cre-location",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 6,
      "circle-color": "#165cb4",
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 2,
    },
  });
  map.addSource("cre-drawing", { type: "geojson", data: emptyGraphics });
  map.addLayer({
    id: "cre-drawn-area",
    type: "fill",
    source: "cre-drawing",
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: { "fill-color": "#78449a", "fill-opacity": 0.18 },
  });
  map.addLayer({
    id: "cre-drawn-path",
    type: "line",
    source: "cre-drawing",
    filter: ["!=", ["geometry-type"], "Point"],
    paint: { "line-color": "#68278a", "line-width": 3 },
  });
  map.addLayer({
    id: "cre-drawn-vertices",
    type: "circle",
    source: "cre-drawing",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 4.5,
      "circle-color": "#68278a",
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#fff",
    },
  });
}

export function parcelGraphics(data: Parcels, selected: string) {
  return {
    ...data,
    features: data.features.map((f) => ({
      ...f,
      properties: {
        ...f.properties,
        parcel_id: String(f.id),
        selected: String(f.id) === selected,
      },
    })),
  };
}

export function locationGraphics(fix: LocationFix | null): FeatureCollection {
  if (!fix) return emptyGraphics;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [accuracyRing(fix.point, fix.accuracy)],
        },
        properties: {},
      },
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: fix.point },
        properties: {},
      },
    ],
  };
}

export function drawingGraphics(
  points: Point[],
  mode: MeasureMode,
): FeatureCollection {
  const result: FeatureCollection = {
    type: "FeatureCollection",
    features: points.map((point) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: point },
      properties: {},
    })),
  };
  if (points.length >= 2) {
    const geometry =
      mode === "area" && points.length >= 3
        ? { type: "Polygon" as const, coordinates: [[...points, points[0]]] }
        : { type: "LineString" as const, coordinates: points };
    result.features.push({ type: "Feature", geometry, properties: {} });
  }
  return result;
}

export function fitParcels(map: LibreMap, data: Parcels) {
  let west = Infinity,
    south = Infinity,
    east = -Infinity,
    north = -Infinity;
  for (const f of data.features) {
    const rings =
      f.geometry.type === "MultiPolygon"
        ? f.geometry.coordinates.flat()
        : f.geometry.coordinates;
    for (const ring of rings)
      for (const [x, y] of ring) {
        west = Math.min(west, x);
        south = Math.min(south, y);
        east = Math.max(east, x);
        north = Math.max(north, y);
      }
  }
  if (west <= east && south <= north) {
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 42, maxZoom: 17, duration: 0 },
    );
  }
}
