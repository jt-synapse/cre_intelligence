// Also served as a browser module to the small, credential-free offline shell.
const SESSION = "cre.field.session";
const PARCEL = "cre.field.parcel";
const SIGNAL = "cre.field.change";
const MAX_COUNT = 24;
const MAX_BYTES = 24 * 1024 * 1024;
const MAX_PHOTO = 5 * 1024 * 1024;

function request(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function transaction(mode, work) {
  const open = indexedDB.open("cre-field-work", 1);
  open.onupgradeneeded = () => {
    open.result.createObjectStore("meta");
    open.result.createObjectStore("pending", { keyPath: "id" });
  };
  const db = await request(open);
  try {
    const tx = db.transaction(["meta", "pending"], mode);
    const completed = new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onabort = () =>
        reject(tx.error || new Error("Field storage is unavailable."));
    });
    try {
      const value = await work(
        tx.objectStore("meta"),
        tx.objectStore("pending"),
      );
      await completed;
      return value;
    } catch (error) {
      try {
        tx.abort();
      } catch {
        /* already finished */
      }
      await completed.catch(() => {});
      throw error;
    }
  } finally {
    db.close();
  }
}

function notify(kind) {
  const value = JSON.stringify([kind, crypto.randomUUID()]);
  try {
    localStorage.setItem(SIGNAL, value);
  } catch {
    /* IDB remains authoritative. */
  }
  window.dispatchEvent(new Event(kind));
}

export function listen(kind, handler) {
  function external(event) {
    if (
      event.key === SIGNAL &&
      event.newValue &&
      JSON.parse(event.newValue)[0] === kind
    )
      handler();
  }
  addEventListener("storage", external);
  addEventListener(kind, handler);
  return () => {
    removeEventListener("storage", external);
    removeEventListener(kind, handler);
  };
}

export function currentSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION));
  } catch {
    return null;
  }
}

// The durable nonce prevents an old tab from reading or writing after an account switch.
export async function bindSession(org, subject, writable, grantHours = 12) {
  const result = await transaction("readwrite", async (meta, queue) => {
    let active = await request(meta.get("active"));
    const changed =
      !active ||
      active.org !== org ||
      active.subject !== subject ||
      active.writable !== writable;
    if (changed) {
      queue.clear();
      active = { org, subject, writable, nonce: crypto.randomUUID() };
    }
    active.hours = Math.max(
      1,
      Math.min(12, Number.isFinite(grantHours) ? grantHours : 12),
    );
    active.expires = Date.now() + active.hours * 3_600_000;
    meta.put(active, "active");
    return { changed, active };
  });
  if (currentSession()?.nonce !== result.active.nonce)
    sessionStorage.removeItem(PARCEL);
  sessionStorage.setItem(SESSION, JSON.stringify(result.active));
  if (result.changed) notify("field-session-change");
  else window.dispatchEvent(new Event("field-session-change"));
  return result.active;
}

export async function clearSession() {
  const previous = currentSession();
  sessionStorage.removeItem(SESSION);
  sessionStorage.removeItem(PARCEL);
  window.dispatchEvent(new Event("field-session-change"));
  if (!previous) return;
  await transaction("readwrite", async (meta, queue) => {
    const active = await request(meta.get("active"));
    if (previous.nonce === active?.nonce) {
      meta.clear();
      queue.clear();
    }
  });
  notify("field-session-change");
}

// Called after a fresh online membership check; a stale tab cannot replace a new session.
export async function renewSession(session) {
  const renewed = await transaction("readwrite", async (meta) => {
    const active = await request(meta.get("active"));
    if (
      !active ||
      !active.expires ||
      active.nonce !== session.nonce ||
      currentSession()?.nonce !== session.nonce
    ) {
      throw new Error("Reconnect and sign in to open field drafts.");
    }
    active.expires = Date.now() + (active.hours || 12) * 3_600_000;
    meta.put(active, "active");
    return active;
  });
  sessionStorage.setItem(SESSION, JSON.stringify(renewed));
  window.dispatchEvent(new Event("field-session-change"));
  return renewed;
}

export async function suspendSession(session) {
  await transaction("readwrite", async (meta) => {
    const active = await request(meta.get("active"));
    if (active?.nonce === session.nonce) {
      active.expires = 0;
      active.nonce = crypto.randomUUID();
      meta.put(active, "active");
      if (currentSession()?.nonce === session.nonce) {
        sessionStorage.setItem(SESSION, JSON.stringify(active));
        sessionStorage.removeItem(PARCEL);
      }
    }
  });
  notify("field-session-change");
}

async function checked(session, mode, work) {
  return transaction(mode, async (meta, queue) => {
    const active = await request(meta.get("active"));
    if (
      !session ||
      !active ||
      active.nonce !== session.nonce ||
      active.subject !== session.subject ||
      active.org !== session.org ||
      !(active.expires > Date.now() && session.expires > Date.now())
    ) {
      throw new Error("Reconnect and sign in to open field drafts.");
    }
    return work(queue, active);
  });
}

export function rememberParcel(session, parcel) {
  sessionStorage.setItem(
    PARCEL,
    JSON.stringify({ nonce: session.nonce, parcel }),
  );
}

export function lastParcel(session) {
  const last = JSON.parse(sessionStorage.getItem(PARCEL) || "null");
  return last?.nonce === session?.nonce ? last?.parcel : null;
}

export async function enqueue(session, parcel, note, photo) {
  note = note.trim();
  if (!parcel || (!note && !photo)) throw new Error("Add a note or a photo.");
  if (note.length > 4000) throw new Error("Use 4,000 characters or fewer.");
  if (
    photo &&
    (!photo.size ||
      photo.size > MAX_PHOTO ||
      !["image/jpeg", "image/png", "image/webp"].includes(photo.type))
  ) {
    throw new Error("Choose a JPEG, PNG, or WebP photo up to 5 MiB.");
  }
  const size = new Blob([note]).size + (photo?.size || 0);
  const entry = {
    id: crypto.randomUUID(),
    parcel,
    note,
    photo,
    size,
    created: Date.now(),
  };
  try {
    await checked(session, "readwrite", async (queue, active) => {
      if (!active.writable)
        throw new Error("Your role has read-only field access.");
      const rows = await request(queue.getAll());
      const bytes = rows.reduce((total, item) => total + item.size, 0);
      if (rows.length >= MAX_COUNT || bytes + size > MAX_BYTES) {
        throw new Error(
          "Field storage is full. Sync or remove pending captures to free space.",
        );
      }
      await request(queue.add(entry));
    });
  } catch (error) {
    if (error?.name === "QuotaExceededError")
      throw new Error("Device storage is full. Free space and try again.");
    throw error;
  }
  notify("field-queue-change");
  return entry;
}

export function pending(session) {
  return checked(session, "readonly", async (queue) =>
    (await request(queue.getAll())).sort((a, b) => a.created - b.created),
  );
}

export async function removeEntry(session, id) {
  await checked(session, "readwrite", (queue) => request(queue.delete(id)));
  notify("field-queue-change");
}

export function pendingCount(session) {
  return checked(session, "readonly", (queue) => request(queue.count()));
}

// A rejected operation keeps its immutable payload and operation ID until an explicit retry.
export async function setFailure(session, id, reason) {
  await checked(session, "readwrite", async (queue) => {
    const row = await request(queue.get(id));
    if (row) {
      if (reason) row.failure = reason;
      else delete row.failure;
      await request(queue.put(row));
    }
  });
  notify("field-queue-change");
}
