"use client";
import { useEffect, useState, type FormEvent } from "react";
import { message, type Api } from "../lib/api";
import type { Property } from "../lib/types";

type Portfolio = { id: string; name: string; property_ids: string[] };
export default function PropertyTools({
  property,
  role,
  curator,
  api,
  onGroup,
}: {
  property: Property;
  role: string;
  curator: boolean;
  api: Api;
  onGroup: () => void;
}) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]),
    [available, setAvailable] = useState<Property[]>([]);
  const [error, setError] = useState(""),
    [pending, setPending] = useState(false),
    [revision, setRevision] = useState(0);
  const [groupOpen, showGroup] = useState(false);
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .get<{ items: Portfolio[] }>("portfolios", ctrl.signal)
      .then((r) => setPortfolios(r.items))
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(message(e));
      });
    return () => ctrl.abort();
  }, [api, revision]);
  useEffect(() => {
    if (!groupOpen) return;
    const ctrl = new AbortController();
    api
      .get<{ items: Property[] }>("properties", ctrl.signal)
      .then((r) => setAvailable(r.items.filter((p) => p.id !== property.id)))
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(message(e));
      });
    return () => ctrl.abort();
  }, [api, property.id, groupOpen]);
  function run(
    e: FormEvent<HTMLFormElement>,
    action: (d: FormData) => Promise<void>,
  ) {
    e.preventDefault();
    if (pending) return;
    const d = new FormData(e.currentTarget);
    setPending(true);
    setError("");
    action(d)
      .catch((e) => setError(message(e)))
      .finally(() => setPending(false));
  }
  return (
    <fieldset disabled={pending} className="forms">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <details className="editor">
        <summary>Property portfolios</summary>
        <div className="portfolio-list">
          {portfolios
            .filter((p) => p.property_ids.includes(property.id))
            .map((p) => (
              <p key={p.id}>{p.name}</p>
            ))}
          {!portfolios.some((p) => p.property_ids.includes(property.id)) && (
            <p>Outside all workspace portfolios.</p>
          )}
        </div>
        {role !== "viewer" && (
          <form
            onSubmit={(e) =>
              run(e, async (d) => {
                let id = String(d.get("existing") || "");
                const newName = String(d.get("name") || "").trim();
                if (newName)
                  id = (
                    await api.send<Portfolio>("portfolios", { name: newName })
                  ).id;
                if (!id)
                  throw new Error("Choose a portfolio or enter a new name.");
                await api.request(
                  "portfolios/" + id + "/properties/" + property.id,
                  { method: "PUT" },
                );
                setRevision((n) => n + 1);
              })
            }
          >
            <label>
              Choose portfolio
              <select name="existing">
                <option value="">Select existing portfolio</option>
                {portfolios
                  .filter((p) => !p.property_ids.includes(property.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              New portfolio name
              <input name="name" maxLength={200} />
            </label>
            <button className="secondary">Add to portfolio</button>
          </form>
        )}
      </details>
      {curator && ["admin", "researcher"].includes(role) && (
        <details
          className="editor"
          onToggle={(e) => showGroup(e.currentTarget.open)}
        >
          <summary>Confirm or group properties</summary>
          <form
            onSubmit={(e) =>
              run(e, async (d) => {
                await api.send("properties/" + property.id + "/grouping", {
                  name: d.get("name"),
                  reason: d.get("reason"),
                  merge_property_ids: d.getAll("merge"),
                });
                onGroup();
              })
            }
          >
            <label>
              Confirmed property name
              <input
                name="name"
                required
                maxLength={200}
                defaultValue={property.name}
              />
            </label>
            <label>
              Properties to merge
              <select multiple name="merge">
                {available.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Basis for grouping
              <textarea required name="reason" maxLength={2000} />
            </label>
            <button className="primary">Confirm grouping</button>
          </form>
        </details>
      )}
    </fieldset>
  );
}
