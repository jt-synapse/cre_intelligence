"use client";
import { useEffect, useRef, useState } from "react";
import type {
  GeoJSONSource,
  Map as LibreMap,
  MapMouseEvent,
  StyleSpecification,
} from "maplibre-gl";
import type { FieldMapPin } from "./FieldPlaces";
import type { Parcels, ParcelShape } from "../lib/types";
import {
  areaMeters,
  nearbyBounds,
  pathMeters,
  type Point,
} from "../lib/map-geometry";
import {
  addMapLayers,
  drawingGraphics,
  fitParcels,
  locationGraphics,
  parcelGraphics,
  type MeasureMode,
} from "./mapLayers";
import { useFieldLocation } from "./useFieldLocation";

const neutralStyle: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "land",
      type: "background",
      paint: { "background-color": "#e9efeb" },
    },
  ],
};
type Candidate = {
  id: string;
  pin: string;
  address: string;
  generation?: string;
};
type MapProps = {
  data: Parcels;
  onSelect: (id: string, generation?: string) => void;
  onArea: (bbox: string) => void;
  onPoint?: (lon: number, lat: number, signal: AbortSignal) => Promise<Parcels>;
  basemap: string | null;
  selected: string;
  fit: number;
  synthetic: boolean;
  outline?: ParcelShape | null;
  related?: Parcels;
  pins?: FieldMapPin[];
  tileTemplate?: string;
  tileHeaders?: Record<string, string>;
};

export default function ParcelMap({
  data,
  onSelect,
  onArea,
  onPoint,
  basemap,
  selected,
  fit,
  synthetic,
  outline,
  pins,
  related,
  tileTemplate,
  tileHeaders,
}: MapProps) {
  const container = useRef<HTMLDivElement>(null),
    map = useRef<LibreMap | null>(null);
  const [styleEpoch, setStyleEpoch] = useState(0);
  const styleVersion = useRef(0);
  const [imagery, setImagery] = useState(Boolean(basemap));
  const [mapMessage, setMapMessage] = useState("");
  const [pickMessage, setPickMessage] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const pendingPick = useRef<AbortController | null>(null);
  const lastFit = useRef(-1);
  const camera = useRef<{ center: Point; zoom: number } | null>(null);
  const [mode, setMode] = useState<MeasureMode>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const location = useFieldLocation((fix, first) => {
    const m = map.current;
    lastFit.current = fit;
    const zoom = first
      ? Math.max(m?.getZoom() ?? 16, 16)
      : (m?.getZoom() ?? 16);
    camera.current = { center: fix.point, zoom };
    m?.jumpTo(camera.current);
    if (first) onArea(nearbyBounds(fix.point, fix.accuracy));
  });
  const live = useRef({
    onPoint,
    onSelect,
    mode,
    tileTemplate,
    tileHeaders,
    stopLocation: location.stop,
  });
  live.current = {
    onPoint,
    onSelect,
    mode,
    tileTemplate,
    tileHeaders,
    stopLocation: location.stop,
  };

  function clearPick() {
    pendingPick.current?.abort();
    pendingPick.current = null;
    setCandidates([]);
    setPickMessage("");
  }
  useEffect(() => {
    clearPick();
  }, [selected, data, mode]);

  useEffect(() => {
    let stopped = false;
    let observer: ResizeObserver | undefined;
    let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
    let usingImagery = Boolean(imagery && basemap);
    // Keep the same viewport when switching between the configured imagery and neutral style.
    setStyleEpoch(0);
    import("maplibre-gl")
      .then(({ Map, NavigationControl, setWorkerUrl }) => {
        if (stopped || !container.current) return;
        setWorkerUrl(window.location.origin + "/map-worker");
        const m = new Map({
          container: container.current,
          style: usingImagery ? basemap! : neutralStyle,
          center: camera.current?.center || [-84.01, 33.96],
          zoom: camera.current?.zoom ?? 10,
          attributionControl: { compact: true },
          canvasContextAttributes: { antialias: true },
          transformRequest: (url, kind) => {
            const template = live.current.tileTemplate;
            const parsed = new URL(url, window.location.href);
            // Only this application's configured XYZ endpoint may receive workspace credentials.
            if (
              kind === "Tile" &&
              template?.startsWith("/v1/tiles/") &&
              parsed.origin === window.location.origin &&
              /^\/v1\/tiles\/[^/]+\/\d+\/\d+\/\d+$/.test(parsed.pathname) &&
              parsed.pathname.split("/").slice(0, 4).join("/") ===
                template.split("/").slice(0, 4).join("/")
            ) {
              return {
                url,
                headers: live.current.tileHeaders,
                cache: "no-store",
              };
            }
            return { url };
          },
        });
        map.current = m;
        m.addControl(
          new NavigationControl({ showCompass: false }),
          "top-right",
        );
        function fallback() {
          if (stopped || !usingImagery) return;
          usingImagery = false;
          setMapMessage("Imagery unavailable. Showing parcel boundaries.");
          setImagery(false);
        }
        if (usingImagery) fallbackTimer = setTimeout(fallback, 6000);
        m.on("style.load", () => {
          if (stopped) return;
          clearTimeout(fallbackTimer);
          addMapLayers(m);
          setStyleEpoch(++styleVersion.current);
        });
        m.on("error", (e) => {
          if (stopped) return;
          const source = "sourceId" in e ? e.sourceId : undefined;
          if (source === "cre-tiles") {
            setMapMessage(
              "Parcel tiles unavailable. Showing parcels from the results list.",
            );
          } else if (typeof source !== "string" || !source.startsWith("cre-")) {
            fallback();
          }
        });
        m.on("movestart", (e) => {
          if (e.originalEvent) live.current.stopLocation();
        });
        m.on("dragstart", () => live.current.stopLocation());
        m.on("click", async (e: MapMouseEvent) => {
          clearPick();
          if (live.current.mode) {
            setPoints((list) => [...list, [e.lngLat.lng, e.lngLat.lat]]);
            return;
          }
          if (!m.getLayer("cre-fill")) return;
          const layers = ["cre-fill", "cre-tiles-fill"].filter((id) =>
            m.getLayer(id),
          );
          const nearby = m.queryRenderedFeatures(
            [
              [e.point.x - 5, e.point.y - 5],
              [e.point.x + 5, e.point.y + 5],
            ],
            { layers },
          );
          const found = new globalThis.Map<string, Candidate>();
          for (const { properties, source } of nearby) {
            const id = properties.parcel_id;
            if (id)
              found.set(String(id), {
                id: String(id),
                pin: properties.primary_pin || "",
                address: properties.address || "",
                generation:
                  properties.reader_version ||
                  (source === "cre-tiles"
                    ? live.current.tileTemplate?.split("/")[3]
                    : undefined),
              });
          }
          const controller = new AbortController();
          pendingPick.current = controller;
          try {
            const lookup = live.current.onPoint;
            let exactIds: string[] = [];
            if (lookup) {
              setPickMessage("Checking parcel…");
              const exact = await lookup(
                e.lngLat.wrap().lng,
                e.lngLat.lat,
                controller.signal,
              );
              if (controller.signal.aborted || stopped) return;
              for (const f of exact.features) {
                const id = String(f.id);
                const rendered = found.get(id);
                if (
                  rendered?.generation &&
                  rendered.generation !== f.properties.reader_version
                ) {
                  setPickMessage(
                    "Parcel boundaries changed. Search this area to refresh the map.",
                  );
                  return;
                }
                exactIds.push(id);
                found.set(id, {
                  id,
                  pin: f.properties.primary_pin,
                  address: f.properties.address || "",
                  generation: f.properties.reader_version,
                });
              }
            } else {
              exactIds = m
                .queryRenderedFeatures(e.point, { layers })
                .map((f) => String(f.properties.parcel_id));
            }
            setPickMessage("");
            const [only] = found.values();
            if (found.size === 1 && exactIds.includes(only.id))
              live.current.onSelect(only.id, only.generation);
            else if (found.size) setCandidates([...found.values()]);
            else
              setPickMessage(
                "No parcel found here. Try another point or search by parcel ID.",
              );
          } catch {
            if (!controller.signal.aborted && !stopped)
              setPickMessage(
                "Parcel lookup unavailable. Choose a parcel from the results list.",
              );
          }
        });
        m.on("mouseenter", "cre-fill", () => {
          m.getCanvas().style.cursor = "pointer";
        });
        m.on("mouseleave", "cre-fill", () => {
          m.getCanvas().style.cursor = "";
        });
        observer = new ResizeObserver(() => m.resize());
        observer.observe(container.current);
      })
      .catch(() => {
        if (!stopped)
          setMapMessage(
            "Interactive map unavailable. Choose a parcel from the results list.",
          );
      });
    return () => {
      stopped = true;
      clearTimeout(fallbackTimer);
      observer?.disconnect();
      pendingPick.current?.abort();
      const m = map.current;
      if (m) {
        camera.current = {
          center: m.getCenter().toArray() as Point,
          zoom: m.getZoom(),
        };
        m.remove();
        map.current = null;
      }
    };
  }, [basemap, imagery]);
  useEffect(() => {
    const m = map.current;
    if (!m?.getSource("cre-parcels")) return;
    m.getSource<GeoJSONSource>("cre-parcels")!.setData(
      parcelGraphics(data, selected),
    );
    if (data.features.length && lastFit.current !== fit) {
      fitParcels(m, data);
      lastFit.current = fit;
    }
  }, [styleEpoch, data, selected, fit]);
  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("cre-fill") || !tileTemplate?.startsWith("/v1/tiles/"))
      return;
    m.addSource("cre-tiles", {
      type: "vector",
      tiles: [window.location.origin + tileTemplate],
      maxzoom: 18,
    });
    m.addLayer(
      {
        id: "cre-tiles-fill",
        type: "fill",
        source: "cre-tiles",
        "source-layer": "parcels",
        paint: { "fill-color": "#428c84", "fill-opacity": 0.24 },
      },
      "cre-fill",
    );
    m.addLayer(
      {
        id: "cre-tiles-line",
        type: "line",
        source: "cre-tiles",
        "source-layer": "parcels",
        paint: { "line-color": "#286960", "line-width": 1.4 },
      },
      "cre-fill",
    );
    return () => {
      if (map.current !== m) return;
      for (const id of ["cre-tiles-line", "cre-tiles-fill"])
        if (m.getLayer(id)) m.removeLayer(id);
      if (m.getSource("cre-tiles")) m.removeSource("cre-tiles");
    };
  }, [styleEpoch, tileTemplate]);
  useEffect(() => {
    const m = map.current;
    if (m?.getLayer("cre-tiles-fill"))
      m.setPaintProperty("cre-tiles-fill", "fill-color", [
        "case",
        ["==", ["get", "parcel_id"], selected],
        "#e59431",
        "#428c84",
      ]);
  }, [styleEpoch, tileTemplate, selected]);
  useEffect(() => {
    map.current
      ?.getSource<GeoJSONSource>("cre-related")
      ?.setData(related || { type: "FeatureCollection", features: [] });
  }, [styleEpoch, related]);
  useEffect(() => {
    map.current?.getSource<GeoJSONSource>("cre-pins")?.setData({
      type: "FeatureCollection",
      features: (pins || []).map((pin) => ({
        type: "Feature",
        properties: {
          parcel_id: pin.parcel_id,
          color: pin.color,
          label: pin.label,
        },
        geometry: { type: "Point", coordinates: pin.point },
      })),
    });
  }, [styleEpoch, pins]);
  useEffect(() => {
    map.current?.getSource<GeoJSONSource>("cre-site")?.setData({
      type: "FeatureCollection",
      features: outline
        ? [{ type: "Feature", properties: {}, geometry: outline }]
        : [],
    });
  }, [styleEpoch, outline]);
  useEffect(() => {
    map.current
      ?.getSource<GeoJSONSource>("cre-location")
      ?.setData(locationGraphics(location.fix));
  }, [styleEpoch, location.fix]);
  useEffect(() => {
    map.current
      ?.getSource<GeoJSONSource>("cre-drawing")
      ?.setData(drawingGraphics(points, mode));
  }, [styleEpoch, mode, points]);

  function measure(next: MeasureMode) {
    setPoints([]);
    setMode(next);
  }
  const units = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  let measurement = "Distance requires two points.";
  if (mode === "area") {
    const area = areaMeters(points);
    if (points.length < 3) measurement = "Area requires three points.";
    else if (area === null)
      measurement =
        "The outline crosses itself. Undo points and trace around the perimeter.";
    else
      measurement =
        "Estimated area " + units.format(area / 4046.8564224) + " acres";
  } else if (points.length >= 2) {
    measurement =
      "Estimated distance " + units.format(pathMeters(points) / 0.3048) + " ft";
  }
  return (
    <section aria-label="Parcel map" className="map-shell">
      <div className="field-controls" role="group" aria-label="Map tools">
        <button
          type="button"
          className="small"
          onClick={() => location.locate(false)}
        >
          Locate me
        </button>
        <button
          type="button"
          className="small"
          aria-pressed={location.following}
          onClick={() =>
            location.following ? location.stop() : location.locate(true)
          }
        >
          {location.following ? "Stop following" : "Follow location"}
        </button>
        <button
          type="button"
          className="small"
          disabled={!styleEpoch}
          aria-expanded={Boolean(mode)}
          onClick={() => measure(mode ? null : "distance")}
        >
          {mode ? "Close measure" : "Measure"}
        </button>
        {basemap && (
          <button
            type="button"
            className="small"
            aria-pressed={imagery}
            onClick={() => {
              setMapMessage("");
              setImagery(!imagery);
            }}
          >
            Imagery
          </button>
        )}
      </div>
      <div className="field-map-frame">
        <div ref={container} className="map" />
        {mode && <span className="map-crosshair" aria-hidden="true" />}
      </div>
      {(mapMessage || location.message || location.fix || pickMessage) && (
        <div role="status" className="field-status">
          {mapMessage && <p>{mapMessage}</p>}
          {location.message && <p>{location.message}</p>}
          {location.fix && (
            <p>
              GPS accuracy ±{Math.round(location.fix.accuracy)} m
              {location.following ? " · Following" : " · Last fix"}
            </p>
          )}
          {pickMessage && <p>{pickMessage}</p>}
        </div>
      )}
      {candidates.length > 0 && (
        <div
          role="group"
          aria-label="Choose a parcel"
          className="field-choices"
        >
          <strong>Choose a parcel near this point</strong>
          {candidates.map((c) => (
            <button
              type="button"
              className="small"
              key={c.id}
              onClick={() => {
                clearPick();
                onSelect(c.id, c.generation);
              }}
            >
              {c.address || "Parcel"} · {c.pin || c.id}
            </button>
          ))}
          <button type="button" className="text-button" onClick={clearPick}>
            Dismiss choices
          </button>
        </div>
      )}
      {mode && (
        <div className="field-measure">
          <div role="group" aria-label="Measurement type">
            {(["distance", "area"] as const).map((value) => (
              <button
                type="button"
                key={value}
                className="small"
                aria-pressed={mode === value}
                onClick={() => measure(value)}
              >
                {value === "distance" ? "Distance" : "Area"}
              </button>
            ))}
          </div>
          <p>
            Tap{" "}
            {mode === "area"
              ? "around the outline in order"
              : "points along the path"}
            .
          </p>
          <output aria-live="polite">{measurement}</output>
          <div>
            <button
              type="button"
              className="small"
              onClick={() => {
                const center = map.current?.getCenter();
                if (center)
                  setPoints((list) => [...list, [center.lng, center.lat]]);
              }}
            >
              Add map center
            </button>
            <button
              type="button"
              className="small"
              disabled={!points.length}
              onClick={() => setPoints((list) => list.slice(0, -1))}
            >
              Undo point
            </button>
          </div>
        </div>
      )}
      <div className="map-foot">
        <span>
          <i className="parcel-swatch" aria-hidden="true" />
          {synthetic
            ? "Synthetic parcel geometry"
            : data.features.length
              ? "County parcel boundaries"
              : "Parcel boundaries"}
          {outline && <small>Dashed outline · Site preview</small>}
          {Boolean(related?.features.length) && (
            <small>Blue outline · Related parcels</small>
          )}
        </span>
        <button
          type="button"
          className="small"
          disabled={!styleEpoch}
          onClick={() => {
            const b = map.current!.getBounds();
            onArea(
              [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
                .map((v) => v.toFixed(6))
                .join(","),
            );
          }}
        >
          Search this area
        </button>
      </div>
    </section>
  );
}
