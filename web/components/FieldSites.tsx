"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { message, type Api } from "../lib/api";
import type { ParcelShape } from "../lib/types";
import styles from "./FieldSites.module.css";

type Pick = {
  id: string;
  primary_pin: string;
  geometry_version_id?: string;
  reader_version?: string;
};
type Member = {
  parcel_id: string;
  geometry_version_id: string;
  primary_pin: string;
};
type Source = {
  parcel_id: string;
  source_record_id: string;
  dataset_key: string;
  publisher: string;
  attribution: string | null;
  observed_at: string;
  locator: unknown;
};
type Result = {
  id?: string;
  revision?: number;
  name?: string;
  reader_version: string;
  members: (Member & Source)[];
  geometry: ParcelShape;
  union_acres: number;
  source_acres: { subtotal: number | string | null; covered_members: number };
  ownership: { known_recorded_parties: number; unresolved_members: number };
  assessment_groups: {
    year: number;
    currency: string;
    subtotal: number | string;
    covered_members: number;
  }[];
  components: string[][];
  point_only_contacts: [string, string][];
  claim_sources: (Source & { predicate: string })[];
};
type SavedSite = { id: string; name: string; revision: number };

function SiteFacts({ result }: { result: Result }) {
  const pin = new Map(result.members.map((m) => [m.parcel_id, m.primary_pin]));
  const covered = (count: number) =>
    `${count} of ${result.members.length} parcels`;
  const source = result.source_acres;
  const format = (value: number | string) =>
    Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
  return (
    <section className={styles.facts} aria-label="Site preview">
      <p>
        <strong>{format(result.union_acres)} acres</strong> · Measured union
      </p>
      <p>
        Source deeded acreage ·{" "}
        {source.subtotal === null
          ? "Unknown"
          : format(source.subtotal) + " acres"}{" "}
        ({covered(source.covered_members)})
      </p>
      {result.components.length > 1 && (
        <div>
          <strong>
            {result.components.length} separate polygon components
          </strong>
          <ul>
            {result.components.map((ids, i) => (
              <li key={i}>{ids.map((id) => pin.get(id)).join(", ")}</li>
            ))}
          </ul>
        </div>
      )}
      {result.point_only_contacts.length > 0 && (
        <p>
          Point-only contacts ·{" "}
          {result.point_only_contacts
            .map(([a, b]) => [pin.get(a), pin.get(b)].join(" / "))
            .join(", ")}
        </p>
      )}
      <p>
        Recorded ownership · {result.ownership.known_recorded_parties}{" "}
        identified parties, {result.ownership.unresolved_members} parcels
        unresolved
      </p>
      {result.assessment_groups.length === 0 ? (
        <p>Assessed value · Unknown</p>
      ) : (
        <ul aria-label="Assessed values by tax year and currency">
          {result.assessment_groups.map((group) => (
            <li key={group.year + group.currency}>
              {group.year} assessed value · {format(group.subtotal)}{" "}
              {group.currency} ({covered(group.covered_members)})
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary>Site sources</summary>
        <ul>
          {[
            ...result.members.map((m) => ({ ...m, predicate: "boundary" })),
            ...result.claim_sources,
          ].map((s, i) => (
            <li key={i}>
              {pin.get(s.parcel_id)} · {s.predicate.replaceAll("_", " ")} ·{" "}
              {s.publisher || s.dataset_key} · {s.observed_at.slice(0, 10)}
              {s.attribution && <> · {s.attribution}</>}
              <small>Record {s.source_record_id}</small>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export default function FieldSites({
  api,
  role,
  parcel,
  onOutline,
}: {
  api: Api;
  role: string;
  parcel: Pick | null;
  onOutline?: (geometry: ParcelShape | null) => void;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [reader, setReader] = useState("");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<SavedSite | null>(null);
  const [saved, setSaved] = useState<SavedSite[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [listVersion, refreshList] = useState(0);
  const [busy, setBusy] = useState<"open" | "preview" | "save" | null>(null);
  const [multi, setMulti] = useState(false);
  const [notice, setNotice] = useState("");
  const lastPick = useRef("");
  const sequence = useRef(0);
  const writer = ["admin", "researcher", "analyst"].includes(role);

  useEffect(() => {
    const controller = new AbortController();
    api
      .get<{ items: SavedSite[] }>("field/sites", controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSaved(data.items);
          setListError("");
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setListError(message(err));
      });
    return () => controller.abort();
  }, [api, listVersion]);
  useEffect(
    () => () => {
      ++sequence.current;
    },
    [],
  );
  useEffect(() => {
    onOutline?.(result?.geometry ?? null);
    return () => onOutline?.(null);
  }, [result, onOutline]);

  const invalidate = useCallback(() => {
    ++sequence.current;
    setResult(null);
    setError("");
    setBusy(null);
    setNotice("");
  }, []);

  const add = useCallback(
    (picked: Pick) => {
      if (members.some((m) => m.parcel_id === picked.id)) return;
      if (!picked.reader_version || !picked.geometry_version_id) {
        setError("Refresh this parcel to load its boundary version.");
        return;
      }
      if (members.length >= 20) {
        setError("A site supports up to 20 parcels.");
        return;
      }
      if (members.length && reader !== picked.reader_version) {
        setError(
          "Choose parcels from one county and reader version. Start a new site to change versions.",
        );
        return;
      }
      invalidate();
      setReader(picked.reader_version);
      setMembers([
        ...members,
        {
          parcel_id: picked.id,
          geometry_version_id: picked.geometry_version_id,
          primary_pin: picked.primary_pin,
        },
      ]);
    },
    [members, reader, invalidate],
  );

  useEffect(() => {
    if (!multi || !parcel || busy === "save" || busy === "open") return;
    const key = parcel.id + "/" + parcel.geometry_version_id;
    if (lastPick.current === key) return;
    lastPick.current = key;
    add(parcel);
  }, [multi, parcel, add, busy]);

  function clear() {
    invalidate();
    setMulti(false);
    setEditing(null);
    setMembers([]);
    setReader("");
    setName("");
  }
  function load(data: Result) {
    setResult(data);
    setMembers(data.members);
    setReader(data.reader_version);
    if (data.id && data.name && data.revision) {
      setEditing({ id: data.id, name: data.name, revision: data.revision });
      setName(data.name);
    }
  }
  async function open(id: string) {
    clear();
    const token = sequence.current;
    setBusy("open");
    try {
      const data = await api.get<Result>("field/sites/" + id);
      if (token === sequence.current) load(data);
    } catch (err) {
      if (token === sequence.current) {
        setError(message(err));
        refreshList((x) => x + 1);
      }
    } finally {
      if (token === sequence.current) setBusy(null);
    }
  }
  async function submit(save: boolean) {
    const token = ++sequence.current;
    setError("");
    setNotice("");
    setBusy(save ? "save" : "preview");
    const body = {
      reader_version: reader,
      members: members.map(({ parcel_id, geometry_version_id }) => ({
        parcel_id,
        geometry_version_id,
      })),
    };
    try {
      const data = save
        ? await api.send<Result>(
            editing ? "field/sites/" + editing.id : "field/sites",
            {
              ...body,
              name: name.trim(),
              ...(editing ? { expected_revision: editing.revision } : {}),
            },
            editing ? "PUT" : "POST",
          )
        : await api.send<Result>("field/sites/preview", body);
      if (token !== sequence.current) return;
      if (save) {
        load(data);
        setMulti(false);
        setNotice("Site saved.");
        refreshList((x) => x + 1);
      } else setResult(data);
    } catch (err) {
      if (token === sequence.current) {
        setResult(null);
        setError(message(err));
      }
    } finally {
      if (token === sequence.current) setBusy(null);
    }
  }
  return (
    <section className={`surface ${styles.card}`} aria-label="Field sites">
      <h2>Field sites</h2>
      <label>
        Saved sites
        <select
          value={editing?.id || ""}
          disabled={busy === "save"}
          onChange={(e) => {
            if (e.target.value) void open(e.target.value);
            else clear();
          }}
        >
          <option value="">New site</option>
          {saved.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} · revision {s.revision}
            </option>
          ))}
        </select>
      </label>
      {listError && (
        <p className="error" role="alert">
          {listError}{" "}
          <button type="button" onClick={() => refreshList((x) => x + 1)}>
            Retry saved sites
          </button>
        </p>
      )}
      {editing && (
        <button
          className="text-button"
          onClick={() => void open(editing.id)}
          disabled={Boolean(busy)}
        >
          Reopen latest revision
        </button>
      )}
      <fieldset className="forms" disabled={busy === "save" || busy === "open"}>
        <label>
          <input
            type="checkbox"
            checked={multi}
            onChange={(e) => {
              lastPick.current = "";
              setMulti(e.target.checked);
            }}
          />{" "}
          Add map selections to site
        </label>
        <button
          className="secondary"
          type="button"
          disabled={!parcel || members.some((m) => m.parcel_id === parcel.id)}
          onClick={() => parcel && add(parcel)}
        >
          Add selected parcel
        </button>
        <ul className={styles.members} aria-label="Site members">
          {members.map((m) => (
            <li key={m.parcel_id}>
              {m.primary_pin}{" "}
              <button
                type="button"
                className="text-button"
                aria-label={"Remove " + m.primary_pin}
                onClick={() => {
                  invalidate();
                  setMembers(
                    members.filter((x) => x.parcel_id !== m.parcel_id),
                  );
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="secondary"
          disabled={!members.length || busy === "preview"}
          onClick={() => void submit(false)}
        >
          Preview site
        </button>
        {(members.length > 0 || editing) && (
          <button className="text-button" type="button" onClick={clear}>
            Start new site
          </button>
        )}
        {result && <SiteFacts result={result} />}
        {writer && members.length > 0 && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (result && name.trim()) void submit(true);
            }}
          >
            <label>
              Site name{" "}
              <input
                value={name}
                required
                maxLength={200}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="primary"
              disabled={!result || !name.trim() || Boolean(busy)}
            >
              {editing ? "Save site revision" : "Save site"}
            </button>
          </form>
        )}
      </fieldset>
      {(busy || notice) && (
        <p role="status">
          {busy === "preview"
            ? "Measuring site…"
            : busy === "save"
              ? "Saving site…"
              : busy === "open"
                ? "Opening site…"
                : notice}
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}
