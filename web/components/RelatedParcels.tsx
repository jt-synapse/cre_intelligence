"use client";
import { useEffect, useState } from "react";
import type { Api } from "../lib/api";
import { message } from "../lib/api";
import { emptyParcels, type Parcel, type Parcels } from "../lib/types";

export default function RelatedParcels({
  api,
  parcel,
  onSelect,
  onRelated,
}: {
  api: Api;
  parcel: Parcel;
  onSelect: (id: string, version?: string) => void;
  onRelated: (data: Parcels) => void;
}) {
  const [mode, setMode] = useState("");
  const [matches, setMatches] = useState<Parcels | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setMatches(null);
    setError("");
    onRelated(emptyParcels);
    if (mode)
      api
        .get<Parcels>(
          "parcels/" +
            parcel.id +
            "/related?mode=" +
            mode +
            "&generation=" +
            parcel.reader_version,
          controller.signal,
        )
        .then((value) => {
          if (!controller.signal.aborted) {
            setMatches(value);
            onRelated(value);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(message(err));
        });
    return () => {
      controller.abort();
      onRelated(emptyParcels);
    };
  }, [api, parcel.id, parcel.reader_version, mode, onRelated]);
  return (
    <section aria-label="Related parcels">
      <label>
        Related parcels{" "}
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="">Choose a relationship</option>
          <option value="party">Same documented owner identity</option>
          <option value="mailing">Shared mailing address</option>
          <option value="control">Common documented controller</option>
        </select>
      </label>
      {mode && !error && !matches && (
        <p role="status">Checking parcel evidence…</p>
      )}
      {error && <p role="alert">{error}</p>}
      {matches && !matches.features.length && (
        <p>No related parcels with this evidence in the current county data.</p>
      )}
      {matches?.features.map((f) => (
        <div key={f.id}>
          <button
            type="button"
            className="text-button"
            onClick={() => onSelect(String(f.id), f.properties.reader_version)}
          >
            {f.properties.address || f.properties.primary_pin}
          </button>
          <small>
            {f.properties.relationship_source} · PIN {f.properties.primary_pin}
          </small>
          <details>
            <summary>Relationship evidence</summary>
            <p>Selected parcel record {f.properties.selected_source}</p>
            <p>Related parcel record {f.properties.related_source}</p>
            {f.properties.control_source && (
              <p>
                Control records {f.properties.control_source} ·{" "}
                {f.properties.related_control_source}
              </p>
            )}
          </details>
        </div>
      ))}
    </section>
  );
}
