"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ApiError, message, type Api } from "../lib/api";
import { replayFields, revalidateFieldSession } from "../lib/fieldQueue";
import {
  bindSession,
  currentSession,
  enqueue,
  listen,
  pending,
  rememberParcel,
  removeEntry,
  suspendSession,
  setFailure,
  pendingCount,
  type FieldDraft,
  type FieldSession,
} from "../lib/fieldStore.mjs";

type Workspace = { api: Api; subject: string; orgId: string; role: string };
type Capture = {
  id: string;
  note: string;
  created_at: string;
  photo_type: string | null;
};
const canWrite = (role: string) =>
  ["admin", "analyst", "researcher"].includes(role);

export function FieldSync({
  api,
  subject,
  orgId,
  role,
  grantHours = 12,
}: Workspace & { grantHours?: number }) {
  const [error, setError] = useState("");
  const [reopen, setReopen] = useState(false);
  const [issues, setIssues] = useState<FieldDraft[]>([]);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/field-sw.js", { scope: "/" })
      .catch(() => setError("Offline reload is unavailable on this browser."));
  }, []);

  useEffect(() => {
    let stopped = false;
    let busy = false;
    let requested = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let delay = 2000;
    let verify = false;
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;
    function reconnect() {
      verify = true;
      void sync();
    }
    function scheduleExpiry(session: FieldSession) {
      clearTimeout(expiryTimer);
      expiryTimer = setTimeout(
        () => {
          setIssues([]);
          reconnect();
        },
        Math.max(1, session.expires - Date.now()),
      );
    }
    let grant: FieldSession | null = null;
    const controller = new AbortController();
    async function sync() {
      if (!grant || stopped || !navigator.onLine) return;
      if (busy) {
        requested = true;
        return;
      }
      busy = true;
      clearTimeout(retryTimer);
      try {
        do {
          requested = false;
          if (verify || grant.expires <= Date.now()) {
            grant = await revalidateFieldSession(api, grant, controller.signal);
            verify = false;
            scheduleExpiry(grant);
            void refreshIssues();
          }
          await replayFields(api, grant, controller.signal);
        } while (requested && !stopped);
        if (!stopped) {
          setError("");
          delay = 2000;
        }
      } catch (err) {
        if (!stopped) {
          setError(message(err));
          // Network errors and unavailable services may include a committed write with a lost response.
          if (err instanceof ApiError && [401, 403].includes(err.status)) {
            setReopen(true);
            await suspendSession(grant).catch(() => {});
          } else if (
            !(err instanceof ApiError) ||
            err.status >= 500 ||
            err.status === 429
          ) {
            retryTimer = setTimeout(sync, delay);
            delay = Math.min(delay * 2, 60_000);
          }
        }
      } finally {
        busy = false;
      }
    }
    let sequence = 0;
    async function refreshIssues() {
      if (!grant || stopped) return;
      const version = ++sequence;
      try {
        const rows = await pending(grant);
        if (!stopped && version === sequence)
          setIssues(rows.filter((row) => row.failure));
      } catch {
        if (!stopped && version === sequence) setIssues([]);
      }
    }
    const unlisten = listen("field-queue-change", () => {
      void refreshIssues();
      void sync();
    });
    function stop() {
      stopped = true;
      setIssues([]);
      clearTimeout(expiryTimer);
      clearTimeout(retryTimer);
      controller.abort();
    }
    const unbind = listen("field-session-change", () => {
      if (!grant) return;
      const local = currentSession();
      if (!local || local.nonce !== grant.nonce) {
        stop();
        return;
      }
      // A switch in another tab also invalidates this tab's durable nonce.
      void pendingCount(local).catch(stop);
    });
    addEventListener("online", reconnect);
    addEventListener("field-retry", sync);
    setError("");
    setReopen(false);
    void bindSession(orgId, subject, canWrite(role), grantHours)
      .then((session) => {
        if (stopped) return;
        grant = session;
        scheduleExpiry(session);
        void refreshIssues();
        void sync();
      })
      .catch((err) => {
        if (!stopped) {
          setReopen(true);
          setError(message(err));
        }
      });
    return () => {
      stop();
      unlisten();
      unbind();
      removeEventListener("online", reconnect);
      removeEventListener("field-retry", sync);
    };
  }, [api, subject, orgId, role, grantHours]);

  async function resolveIssue(id: string, discard: boolean) {
    const session = currentSession();
    if (session?.subject !== subject || session.org !== orgId) return;
    if (discard && !window.confirm("Discard this pending field capture?"))
      return;
    try {
      if (discard) await removeEntry(session, id);
      else await setFailure(session, id, null);
    } catch (err) {
      setError(message(err));
    }
  }
  return (
    <>
      {error && (
        <div className="error" role="status">
          {error}{" "}
          {reopen ? (
            <a href="/">Reopen workspace</a>
          ) : (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("field-retry"))}
            >
              Retry field sync
            </button>
          )}
        </div>
      )}
      {issues.length > 0 && (
        <section className="error" aria-label="Captures needing attention">
          <h3>Captures needing attention</h3>
          {issues.map((row) => (
            <article key={row.id}>
              <p>{row.note || "Field photo"}</p>
              <small>Parcel {row.parcel}</small>
              <p>{row.failure}</p>
              <button
                type="button"
                onClick={() => void resolveIssue(row.id, false)}
              >
                Retry capture
              </button>{" "}
              <button
                type="button"
                onClick={() => void resolveIssue(row.id, true)}
              >
                Discard capture
              </button>
            </article>
          ))}
        </section>
      )}
    </>
  );
}

function SavedCapture({
  row,
  api,
  path,
}: {
  row: Capture;
  api: Api;
  path: string;
}) {
  const [show, setShow] = useState(false);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!show) return;
    const ctrl = new AbortController();
    let objectUrl = "";
    setError("");
    void api
      .request(path + "/" + row.id + "/photo", { signal: ctrl.signal })
      .then((r) => r.blob())
      .then((blob) => {
        if (ctrl.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setError(message(err));
      });
    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl("");
    };
  }, [api, row.id, path, show]);
  return (
    <article className="finding">
      <small>{new Date(row.created_at).toLocaleString()}</small>
      {row.note && <p>{row.note}</p>}
      {row.photo_type && (
        <button type="button" onClick={() => setShow(!show)}>
          {show ? "Hide photo" : "View photo"}
        </button>
      )}
      {url && (
        <img
          src={url}
          alt="Saved field photo"
          style={{ display: "block", maxWidth: "100%", maxHeight: "20rem" }}
        />
      )}
      {error && <p role="alert">{error}</p>}
    </article>
  );
}

export default function FieldCapture({
  api,
  subject,
  orgId,
  role,
  parcelId,
}: Workspace & { parcelId: string }) {
  const path = `parcels/${parcelId}/field-captures`;
  const [grant, setGrant] = useState<FieldSession | null>(null);
  const [drafts, setDrafts] = useState<FieldDraft[]>([]);
  const [saved, setSaved] = useState<Capture[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let sequence = 0;
    let expiry: ReturnType<typeof setTimeout>;
    async function refresh() {
      const version = ++sequence;
      clearTimeout(expiry);
      const session = currentSession();
      if (session?.subject !== subject || session.org !== orgId) {
        setGrant(null);
        setDrafts([]);
        return;
      }
      try {
        const items = await pending(session);
        if (sequence !== version) return;
        rememberParcel(session, parcelId);
        setGrant(session);
        setDrafts(items.filter((item) => item.parcel === parcelId));
        expiry = setTimeout(refresh, Math.max(1, session.expires - Date.now()));
      } catch {
        if (sequence === version) {
          setGrant(null);
          setDrafts([]);
          setSaved([]);
          setMore(false);
        }
      }
    }
    void refresh();
    const queue = listen("field-queue-change", refresh);
    const changed = listen("field-session-change", refresh);
    return () => {
      ++sequence;
      clearTimeout(expiry);
      queue();
      changed();
    };
  }, [parcelId, subject, orgId]);
  useEffect(() => {
    function sync() {
      setOffset(0);
      setRevision((i) => i + 1);
    }
    addEventListener("field-synced", sync);
    addEventListener("online", sync);
    return () => {
      removeEventListener("field-synced", sync);
      removeEventListener("online", sync);
    };
  }, []);
  useEffect(() => {
    const ctrl = new AbortController();
    if (!navigator.onLine) return;
    void api
      .get<{ items: Capture[]; more: boolean }>(
        path + "?offset=" + offset,
        ctrl.signal,
      )
      .then((page) => {
        if (ctrl.signal.aborted) return;
        setSaved(page.items);
        setMore(page.more);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
            setSaved([]);
            setMore(false);
          }
          setError(message(err));
        }
      });
    return () => ctrl.abort();
  }, [api, path, offset, revision]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!grant || saving) return;
    const form = event.currentTarget;
    const note = form.elements.namedItem("note") as HTMLTextAreaElement;
    const photo = form.elements.namedItem("photo") as HTMLInputElement;
    setSaving(true);
    setError("");
    try {
      await enqueue(grant, parcelId, note.value, photo.files?.[0] || null);
      form.reset();
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="editor" aria-label="Field captures">
      <h3>Field captures</h3>
      {canWrite(role) && (
        <form onSubmit={submit}>
          <label>
            Field note
            <textarea name="note" maxLength={4000} rows={3} />
          </label>
          <label>
            Field photo
            <input
              name="photo"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
            />
          </label>
          <button className="primary" disabled={!grant || saving}>
            Save field capture
          </button>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {drafts.map((draft) => (
        <article className="finding" key={draft.id}>
          <small>Pending sync{draft.photo ? " · Photo attached" : ""}</small>
          {draft.note && <p>{draft.note}</p>}
          <button
            type="button"
            onClick={() => {
              if (
                grant &&
                window.confirm("Discard this pending field capture?")
              ) {
                void removeEntry(grant, draft.id).catch((err) =>
                  setError(message(err)),
                );
              }
            }}
          >
            Discard pending capture
          </button>
        </article>
      ))}
      {saved.map((row) => (
        <SavedCapture key={row.id} row={row} api={api} path={path} />
      ))}
      {(more || offset > 0) && (
        <div>
          {offset > 0 && (
            <button onClick={() => setOffset((n) => Math.max(0, n - 50))}>
              Newer captures
            </button>
          )}
          {more && (
            <button onClick={() => setOffset((n) => n + 50)}>
              Older captures
            </button>
          )}
        </div>
      )}
    </section>
  );
}
