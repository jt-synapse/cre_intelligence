"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { message, type Api } from "../lib/api";

const colors = {
  teal: "#007461",
  blue: "#26649d",
  amber: "#916314",
  violet: "#74519d",
  rose: "#a64767",
  slate: "#586777",
};
type Color = keyof typeof colors;
type Folder = { id: string; name: string; color: Color };
type Pin = {
  parcel_id: string;
  label: string;
  primary_pin: string;
  folder_id: string | null;
  last_visited_at: string | null;
  point: [number, number];
};
type Places = { folders: Folder[]; pins: Pin[] };
type Pick = { id: string; primary_pin: string };
type Visit = { created_by: string; visited_at: string };
export type FieldMapPin = {
  parcel_id: string;
  label: string;
  color: string;
  point: [number, number];
};
const empty: Places = { folders: [], pins: [] };
function dateLabel(instant: string) {
  return new Date(instant).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function ParcelActions({
  api,
  parcel,
  folders,
  pin,
  writer,
  saved,
}: {
  api: Api;
  parcel: Pick;
  folders: Folder[];
  pin?: Pin;
  writer: boolean;
  saved: () => void;
}) {
  const [visits, setVisits] = useState<Visit[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, reload] = useState(0);
  const operation = useRef<string | null>(null);
  const path = "field/places/parcels/" + parcel.id;
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .get<{ items: Visit[] }>(path + "/visits", ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setVisits(data.items);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setError(message(err));
      });
    return () => ctrl.abort();
  }, [api, path, version]);
  async function write(action: () => Promise<void>) {
    if (busy) return;
    if (!navigator.onLine) {
      setError("Connect to save field places or visits.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }
  function pinParcel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void write(async () => {
      await api.send(
        path + "/pin",
        {
          label: String(data.get("label")).trim(),
          folder_id: data.get("folder") || null,
        },
        "PUT",
      );
      setNotice("Parcel pin saved.");
      saved();
    });
  }
  function visit() {
    void write(async () => {
      operation.current ??= crypto.randomUUID();
      await api.send(path + "/visits", { operation_id: operation.current });
      operation.current = null;
      setNotice("Visit recorded.");
      reload((x) => x + 1);
      saved();
    });
  }
  return (
    <div>
      <h3>{parcel.primary_pin}</h3>
      {writer && (
        <fieldset className="forms" disabled={busy}>
          <details className="editor">
            <summary>{pin ? "Edit parcel pin" : "Pin selected parcel"}</summary>
            <form
              key={JSON.stringify([pin?.label, pin?.folder_id])}
              onSubmit={pinParcel}
            >
              <label>
                Pin label
                <input
                  name="label"
                  defaultValue={pin?.label || parcel.primary_pin}
                  maxLength={120}
                  required
                />
              </label>
              <label>
                Pin folder
                <select name="folder" defaultValue={pin?.folder_id || ""}>
                  <option value="">Unfiled</option>
                  {folders.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} · {f.color}
                    </option>
                  ))}
                </select>
              </label>
              <button className="primary">Save pin</button>
            </form>
          </details>
          <button className="secondary" type="button" onClick={visit}>
            Record visit now
          </button>
        </fieldset>
      )}
      {visits.length > 0 && (
        <details>
          <summary>Recent visits ({visits.length})</summary>
          <ul>
            {visits.map((v, i) => (
              <li key={i}>
                <time dateTime={v.visited_at}>{dateLabel(v.visited_at)}</time> ·{" "}
                {v.created_by}
              </li>
            ))}
          </ul>
        </details>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}

export default function FieldPlaces({
  api,
  role,
  parcel,
  onSelect,
  onPins,
}: {
  api: Api;
  role: string;
  parcel: Pick | null;
  onSelect: (id: string) => void;
  onPins?: (pins: FieldMapPin[]) => void;
}) {
  const [places, setPlaces] = useState<Places>(empty);
  const [filter, setFilter] = useState("*");
  const [online, setOnline] = useState(true);
  const [version, reload] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const writer = ["admin", "analyst", "researcher"].includes(role);
  const folders = places.folders;
  useEffect(() => {
    const update = () => {
      setOnline(navigator.onLine);
      if (!navigator.onLine) {
        setPlaces(empty);
        setNotice("");
        setError("");
      }
    };
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    if (!online) return;
    const ctrl = new AbortController();
    api
      .get<Places>("field/places", ctrl.signal)
      .then((result) => {
        if (!ctrl.signal.aborted) {
          setPlaces(result);
          setError("");
        }
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setPlaces(empty);
          setError(message(err));
        }
      });
    return () => ctrl.abort();
  }, [api, online, version]);
  useEffect(() => {
    const byId = new Map(places.folders.map((f) => [f.id, f]));
    onPins?.(
      places.pins.map((p) => ({
        parcel_id: p.parcel_id,
        label: p.label,
        point: p.point,
        color: colors[byId.get(p.folder_id || "")?.color || "slate"],
      })),
    );
    return () => onPins?.([]);
  }, [places, onPins]);
  async function addFolder(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!navigator.onLine || busy) return;
    const form = e.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const folder = await api.send<Folder>("field/places/folders", {
        name: data.get("name"),
        color: data.get("color"),
      });
      setNotice(folder.name + " folder ready.");
      form.reset();
      reload((x) => x + 1);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }
  const pins = places.pins.filter(
    (p) => filter === "*" || (p.folder_id || "") === filter,
  );
  return (
    <section className="surface inspector" aria-label="Saved field places">
      <h2>Saved field places</h2>
      {!online ? (
        <p role="status">Connect to view folders and pins or record a visit.</p>
      ) : (
        <>
          {writer && (
            <details className="editor">
              <summary>Create field folder</summary>
              <form onSubmit={addFolder}>
                <label>
                  Folder name
                  <input name="name" maxLength={80} required />
                </label>
                <label>
                  Folder color
                  <select name="color">
                    {Object.keys(colors).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <button className="primary" disabled={busy}>
                  Create folder
                </button>
              </form>
            </details>
          )}
          <label className="record-picker">
            Saved pins
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="*">All folders</option>
              <option value="">Unfiled</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} · {f.color}
                </option>
              ))}
            </select>
          </label>
          {pins.length > 0 ? (
            <div className="list">
              {pins.map((p) => {
                const folder = folders.find((f) => f.id === p.folder_id);
                return (
                  <button
                    className="result"
                    key={p.parcel_id}
                    onClick={() => onSelect(p.parcel_id)}
                    aria-pressed={parcel?.id === p.parcel_id}
                  >
                    <strong>
                      <span
                        aria-hidden
                        style={{ color: colors[folder?.color || "slate"] }}
                      >
                        ●{" "}
                      </span>
                      {p.label}
                    </strong>
                    <small>
                      {p.primary_pin} · {folder?.name || "Unfiled"}
                      {p.last_visited_at &&
                        " · Visited " + dateLabel(p.last_visited_at)}
                    </small>
                  </button>
                );
              })}
            </div>
          ) : (
            <p>No saved pins in this folder.</p>
          )}
          {parcel && (
            <ParcelActions
              key={parcel.id}
              api={api}
              parcel={parcel}
              folders={folders}
              pin={places.pins.find((p) => p.parcel_id === parcel.id)}
              writer={writer}
              saved={() => reload((x) => x + 1)}
            />
          )}
          {notice && <p role="status">{notice}</p>}
          {error && (
            <p role="alert" className="error">
              {error}{" "}
              <button className="small" onClick={() => reload((x) => x + 1)}>
                Reload places
              </button>
            </p>
          )}
        </>
      )}
    </section>
  );
}
