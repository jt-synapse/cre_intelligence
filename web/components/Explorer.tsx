"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { type Api, message, rows } from "../lib/api";
import {
  display,
  emptyParcels,
  title,
  type Parcel,
  type ParcelShape,
  type Parcels,
  type Property,
  type Saved,
} from "../lib/types";
import ParcelMap from "./ParcelMap";
import Casework from "./Casework";
import { publicSourceURL } from "../lib/proxy.mjs";
import PropertyTools from "./PropertyTools";
import FieldCapture from "./FieldCapture";
import FieldSites from "./FieldSites";
import FieldPlaces, { type FieldMapPin } from "./FieldPlaces";
import RelatedParcels from "./RelatedParcels";
import fieldStyles from "./field.module.css";

type Selection = {
  kind: "parcel" | "property";
  id: string;
  generation?: string;
};
const panels = [
  "Record",
  "Investigations",
  "Opportunities",
  "Financials",
  "Reports",
] as const;
export type Panel = (typeof panels)[number];
export default function Explorer({
  api,
  role,
  basemap,
  curator,
  orgId,
  subject,
  tileHeaders,
}: {
  api: Api;
  role: string;
  basemap: string | null;
  curator: boolean;
  subject: string;
  orgId: string;
  tileHeaders: Record<string, string>;
}) {
  const [view, setView] = useState<"explore" | "saved">("explore"),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("");
  const [data, setData] = useState<Parcels>(emptyParcels),
    [saved, setSaved] = useState<Saved[]>([]),
    [fit, setFit] = useState(0);
  const [selection, setSelection] = useState<Selection | null>(() => {
      const q = new URLSearchParams(location.search);
      const property = q.get("property");
      const parcel = q.get("parcel");
      return property
        ? { kind: "property", id: property }
        : parcel
          ? { kind: "parcel", id: parcel }
          : null;
    }),
    [parcel, setParcel] = useState<Parcel | null>(null),
    [property, setProperty] = useState<Property | null>(null);
  const [expanded, setExpanded] = useState(
    () => !window.matchMedia("(max-width: 650px)").matches,
  );
  const [pins, setPins] = useState<FieldMapPin[]>([]);
  const [related, setRelated] = useState(emptyParcels);
  const [outline, setOutline] = useState<ParcelShape | null>(null);
  const inspector = useRef<HTMLElement>(null);
  const [candidate, setCandidate] = useState("");
  const [panel, setPanel] = useState<Panel>("Record"),
    [error, setError] = useState(""),
    [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(false),
    [loadingDetail, setLoadingDetail] = useState(false),
    [saving, setSaving] = useState(false);
  const [savedVersion, setSavedVersion] = useState(0),
    [saveError, setSaveError] = useState("");
  function select(value: Selection | null) {
    setSelection(value);
    setParcel(null);
    setProperty(null);
    setExpanded(
      value?.kind === "property" ||
        !window.matchMedia("(max-width: 650px)").matches,
    );
    if (value && window.matchMedia("(max-width: 650px)").matches)
      requestAnimationFrame(() =>
        inspector.current?.scrollIntoView({ block: "start" }),
      );
    const url = new URL(window.location.href);
    url.searchParams.delete("parcel");
    url.searchParams.delete("property");
    if (value) url.searchParams.set(value.kind, value.id);
    window.history.replaceState({}, "", url);
  }
  const synthetic = data.features.some(
    (f) => f.properties.county_fips === "99001",
  );
  const current = useRef(selection);
  current.current = selection;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    async function load() {
      try {
        if (view === "saved") {
          const list = await api.get<Saved[] | { items: Saved[] }>(
            "workspace/saves",
            controller.signal,
          );
          if (!controller.signal.aborted) setSaved(rows(list));
        } else {
          const result = await api.get<Parcels>(
            "parcels" + (filter ? "?" + filter : ""),
            controller.signal,
          );
          if (!controller.signal.aborted) {
            setData(result);
            if (!filter.startsWith("bbox=")) setFit((v) => v + 1);
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(message(e));
          setData(emptyParcels);
          setSaved([]);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [api, view, filter, savedVersion]);
  useEffect(() => {
    const controller = new AbortController();
    setParcel(null);
    setProperty(null);
    setPanel("Record");
    setDetailError("");
    setSaveError("");
    setCandidate("");
    if (selection) {
      setLoadingDetail(true);
      (async () => {
        try {
          if (selection.kind === "parcel") {
            const p = await api.get<Parcel>(
              "parcels/" +
                selection.id +
                "?" +
                new URLSearchParams({
                  summary: String(!expanded),
                  ...(selection.generation
                    ? { generation: selection.generation }
                    : {}),
                }),
              controller.signal,
            );
            if (!controller.signal.aborted) setParcel(p);
            if (p.property_id && expanded) {
              const linked = await api.get<Property>(
                "properties/" + p.property_id,
                controller.signal,
              );
              if (!controller.signal.aborted) {
                const selected = linked.parcels.find(
                  (member) => member.id === p.id,
                );
                if (selected?.reader_version !== p.reader_version)
                  throw new Error(
                    "Parcel data changed. Refresh the map and select the parcel again.",
                  );
                setProperty(linked);
              }
            }
          } else {
            const p = await api.get<Property>(
              "properties/" + selection.id,
              controller.signal,
            );
            if (!controller.signal.aborted) {
              setProperty(p);
              setParcel(p.parcels[0] || null);
            }
          }
        } catch (e) {
          if (!controller.signal.aborted) setDetailError(message(e));
        } finally {
          if (!controller.signal.aborted) setLoadingDetail(false);
        }
      })();
    } else setLoadingDetail(false);
    return () => controller.abort();
  }, [api, selection, expanded]);
  const pickParcel = useCallback(
    (id: string, generation?: string) =>
      select({
        kind: "parcel",
        id,
        generation:
          generation ||
          data.features.find((f) => String(f.id) === id)?.properties
            .reader_version,
      }),
    [data],
  );
  const pickPoint = useCallback(
    (lon: number, lat: number, signal: AbortSignal) =>
      api.get<Parcels>("parcels?point=" + lon + "," + lat, signal),
    [api],
  );
  const generations = new Set(
    data.features.map((f) => f.properties.reader_version),
  );
  const generation =
    generations.size === 1
      ? data.features[0]?.properties.reader_version
      : undefined;
  const propertyId = property?.id || parcel?.property_id || "";
  async function save() {
    if (!parcel) return;
    const starting = selection;
    setSaving(true);
    setSaveError("");
    try {
      const s = await api.send<{ property_id: string }>("workspace/saves", {
        parcel_id: parcel.id,
        ...(candidate ? { property_id: candidate } : {}),
      });
      setSavedVersion((n) => n + 1);
      if (current.current === starting)
        select({ kind: "property", id: s.property_id });
    } catch (e) {
      if (current.current === starting) setSaveError(message(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="shell">
      <aside className="rail">
        <div className="eyebrow">Workspace</div>
        <nav aria-label="Workspace views">
          <button
            aria-current={view === "explore" ? "page" : undefined}
            onClick={() => {
              setView("explore");
              select(null);
            }}
          >
            Parcel explorer
          </button>
          <button
            aria-current={view === "saved" ? "page" : undefined}
            onClick={() => {
              setView("saved");
              select(null);
            }}
          >
            Saved properties
          </button>
        </nav>
        <div className="region">
          <span className="eyebrow">Coverage</span>
          <strong>{synthetic ? "Synthetic parcels" : "Parcel coverage"}</strong>
          <span>
            {synthetic ? "Local test coverage" : "Authorized sources"}
          </span>
        </div>
      </aside>
      <main id="work" className="content">
        <div className="page-head">
          <div className="eyebrow">Property research</div>
          <h1>{view === "explore" ? "Parcel explorer" : "Saved properties"}</h1>
        </div>
        {view === "explore" && (
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              setFilter(
                query.trim() ? "q=" + encodeURIComponent(query.trim()) : "",
              );
            }}
          >
            <label className="sr" htmlFor="search">
              Search parcels by address, owner or parcel identifier
            </label>
            <input
              type="search"
              id="search"
              placeholder="Street address, owner or parcel ID"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="primary">Search</button>
          </form>
        )}
        {error && (
          <p className="error" role="alert">
            {error}{" "}
            <button
              className="small"
              onClick={() => setSavedVersion((n) => n + 1)}
            >
              Retry
            </button>
          </p>
        )}
        {view === "explore" ? (
          <div className="explorer-grid">
            <section className="results">
              <h2>
                Parcels <span>{loading ? "…" : data.features.length}</span>
              </h2>
              <div className="list">
                {!loading && !data.features.length && (
                  <p>No matching parcels.</p>
                )}
                {data.features.map((f) => (
                  <button
                    className="result"
                    aria-pressed={
                      selection?.kind === "parcel" &&
                      selection.id === String(f.id)
                    }
                    key={f.id}
                    onClick={() => pickParcel(String(f.id))}
                  >
                    <strong>
                      {f.properties.address || "Address unavailable"}
                    </strong>
                    <small>PIN {f.properties.primary_pin}</small>
                  </button>
                ))}
              </div>
            </section>
            <ParcelMap
              data={data}
              synthetic={synthetic}
              selected={
                selection?.kind === "parcel" ? selection.id : parcel?.id || ""
              }
              onSelect={pickParcel}
              basemap={basemap}
              fit={fit}
              pins={pins}
              related={related}
              outline={outline}
              onPoint={pickPoint}
              tileTemplate={
                generation && !filter.startsWith("q=")
                  ? "/v1/tiles/" + generation + "/{z}/{x}/{y}"
                  : undefined
              }
              tileHeaders={tileHeaders}
              onArea={(bbox) => {
                setQuery("");
                setFilter("bbox=" + encodeURIComponent(bbox));
                setSavedVersion((v) => v + 1);
              }}
            />
          </div>
        ) : (
          <section className="surface saved-list">
            <h2>
              Workspace properties <span>{loading ? "…" : saved.length}</span>
            </h2>
            {!loading && !saved.length && (
              <p>Save a parcel in the explorer to begin a property record.</p>
            )}
            {saved.map((s) => (
              <button
                className="result"
                key={s.property_id}
                onClick={() => select({ kind: "property", id: s.property_id })}
              >
                <strong>{s.name || "Unnamed property"}</strong>
                <small>{title(s.property_status)}</small>
              </button>
            ))}
          </section>
        )}
        {selection && (
          <section
            ref={inspector}
            className="inspector surface"
            aria-label="Selected record"
          >
            <div className="section-head">
              <div>
                <div className="eyebrow">
                  Selected {property ? "property" : "parcel"}
                </div>
                <h2>
                  {property?.name ||
                    parcel?.address ||
                    parcel?.primary_pin ||
                    "Property record"}
                </h2>
              </div>
              <button className="small" onClick={() => select(null)}>
                Close record
              </button>
            </div>
            {loadingDetail ? (
              <p role="status">Loading record…</p>
            ) : detailError ? (
              <div role="alert">
                <p className="error">{detailError}</p>
                <button
                  onClick={() => {
                    select(null);
                    setSavedVersion((v) => v + 1);
                  }}
                >
                  Refresh parcels
                </button>
              </div>
            ) : (
              <>
                {parcel && (
                  <p className="meta">
                    PIN {parcel.primary_pin} <span>·</span>{" "}
                    {property
                      ? title(property.property_status)
                      : "Ungrouped parcel"}
                  </p>
                )}
                {parcel && (
                  <div className={fieldStyles.summary}>
                    <strong>Assessor-listed owner</strong>
                    {parcel.owners?.length ? (
                      parcel.owners.map((owner) => (
                        <div key={owner.source_record_id}>
                          {owner.name}{" "}
                          <small>
                            {owner.dataset_key} ·{" "}
                            {owner.observed_at.slice(0, 10)} ·{" "}
                            {title(owner.verification_state)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <span>Ownership unavailable</span>
                    )}
                    {parcel.map_destination && (
                      <div>
                        <a
                          target="_blank"
                          rel="noreferrer"
                          href={
                            "https://www.google.com/maps/dir/?api=1&destination=" +
                            encodeURIComponent(
                              [...parcel.map_destination.coordinates]
                                .reverse()
                                .join(","),
                            )
                          }
                        >
                          Directions to parcel
                        </a>
                        <small>
                          Destination is inside the parcel. Confirm the entrance
                          before visiting.
                        </small>
                      </div>
                    )}
                    <small>
                      Boundary · {String(parcel.dataset_key)} ·{" "}
                      {String(parcel.observed_at).slice(0, 10)}
                    </small>
                  </div>
                )}
                {!expanded && (
                  <button
                    className="secondary"
                    onClick={() => setExpanded(true)}
                  >
                    Open full record
                  </button>
                )}
                {expanded && (
                  <>
                    {parcel?.property_candidates &&
                      parcel.property_candidates.length > 1 && (
                        <label className="record-picker">
                          Linked property
                          <select
                            value={candidate}
                            onChange={(e) => setCandidate(e.target.value)}
                          >
                            <option value="">Choose a property</option>
                            {parcel.property_candidates.map((id) => (
                              <option value={id} key={id}>
                                {id}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    {view === "explore" && parcel && role !== "viewer" && (
                      <button
                        className="secondary"
                        disabled={
                          saving ||
                          Boolean(
                            parcel.property_candidates &&
                            parcel.property_candidates.length > 1 &&
                            !candidate,
                          )
                        }
                        onClick={() => void save()}
                      >
                        {saving
                          ? "Saving…"
                          : propertyId || candidate
                            ? "Save property to workspace"
                            : "Save as provisional property"}
                      </button>
                    )}
                    {saveError && (
                      <p className="error" role="alert">
                        {saveError}
                      </p>
                    )}
                    {propertyId && (
                      <nav aria-label="Property sections" className="tabs">
                        {panels
                          .filter(
                            (t) =>
                              role !== "viewer" ||
                              !["Investigations", "Reports"].includes(t),
                          )
                          .map((t) => (
                            <button
                              aria-current={t === panel ? "page" : undefined}
                              key={t}
                              onClick={() => setPanel(t)}
                            >
                              {t}
                            </button>
                          ))}
                      </nav>
                    )}
                    {panel === "Record" ? (
                      <>
                        {property && (
                          <PropertyTools
                            property={property}
                            role={role}
                            curator={curator}
                            api={api}
                            onGroup={() => {
                              setSavedVersion((v) => v + 1);
                              select({ kind: "property", id: property.id });
                            }}
                          />
                        )}
                        {(property?.parcels || (parcel ? [parcel] : [])).map(
                          (p) => (
                            <section className="parcel-detail" key={p.id}>
                              <h3>
                                {p.address || "Parcel"}{" "}
                                <small>{p.primary_pin}</small>
                              </h3>
                              <h4>Source evidence</h4>
                              {!p.claims?.length ? (
                                <p>No accessible claims for this parcel.</p>
                              ) : (
                                <div className="table-scroll">
                                  <table>
                                    <thead>
                                      <tr>
                                        <th>Observation</th>
                                        <th>Claim</th>
                                        <th>Evidence</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {p.claims.map((c) => (
                                        <tr key={c.id}>
                                          <td>{title(c.predicate)}</td>
                                          <td>
                                            {display(c.value)}
                                            <small>
                                              {title(c.verification_state)}
                                            </small>
                                          </td>
                                          <td>
                                            <details>
                                              <summary>{c.dataset_key}</summary>
                                              <small>
                                                {String(
                                                  c.observed_at || "",
                                                ).slice(0, 10)}{" "}
                                                · {display(c.locator)}
                                              </small>
                                              <small>
                                                {c.publisher} {c.attribution}
                                              </small>
                                              {publicSourceURL(
                                                c.source_origin,
                                              ) && (
                                                <a
                                                  href={
                                                    publicSourceURL(
                                                      c.source_origin,
                                                    )!
                                                  }
                                                  target="_blank"
                                                  rel="noopener noreferrer"
                                                >
                                                  Open source
                                                </a>
                                              )}
                                              <small>
                                                Record {c.source_record_id}
                                              </small>
                                              {c.run_id && (
                                                <small>Import {c.run_id}</small>
                                              )}
                                              {c.content_sha256 && (
                                                <small>
                                                  SHA-256 {c.content_sha256}
                                                </small>
                                              )}
                                            </details>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                              <h4>Site screening</h4>
                              {p.screening?.length ? (
                                p.screening.map((s, i) => (
                                  <p key={i}>{display(s)}</p>
                                ))
                              ) : (
                                <p>
                                  No screening results available for this
                                  parcel.
                                </p>
                              )}
                            </section>
                          ),
                        )}
                      </>
                    ) : (
                      <Casework
                        key={propertyId + "-" + panel}
                        propertyId={propertyId}
                        panel={panel}
                        api={api}
                        role={role}
                      />
                    )}
                  </>
                )}
                {parcel && (
                  <FieldCapture
                    key={"capture:" + parcel.id}
                    api={api}
                    parcelId={parcel.id}
                    orgId={orgId}
                    subject={subject}
                    role={role}
                  />
                )}
                {parcel && (
                  <RelatedParcels
                    key={"related:" + parcel.id}
                    api={api}
                    parcel={parcel}
                    onSelect={pickParcel}
                    onRelated={setRelated}
                  />
                )}
              </>
            )}
          </section>
        )}
        <FieldPlaces
          api={api}
          role={role}
          parcel={detailError ? null : parcel}
          onSelect={pickParcel}
          onPins={setPins}
        />
        <FieldSites
          onOutline={setOutline}
          api={api}
          role={role}
          parcel={detailError ? null : parcel}
        />
      </main>
    </div>
  );
}
