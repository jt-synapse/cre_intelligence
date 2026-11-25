import { ApiError, type Api } from "./api";
import type { Member } from "./types";
import {
  clearSession,
  currentSession,
  pendingCount,
  renewSession,
  pending,
  removeEntry,
  setFailure,
  type FieldDraft,
  type FieldSession,
} from "./fieldStore.mjs";

export const clearFieldSession = clearSession;

export async function pendingFieldCount() {
  const session = currentSession();
  return session ? pendingCount(session) : 0;
}

export async function revalidateFieldSession(
  api: Api,
  session: FieldSession,
  signal: AbortSignal,
) {
  const member = await api.get<Member>("me", signal);
  const membership = member.organizations.find((org) => org.id === session.org);
  if (
    !membership ||
    member.subject !== session.subject ||
    ["admin", "analyst", "researcher"].includes(membership.role) !==
      session.writable
  ) {
    throw new ApiError(
      403,
      "Field access changed. Reopen the workspace to check your permissions.",
    );
  }
  return renewSession(session);
}

async function upload(api: Api, draft: FieldDraft, signal: AbortSignal) {
  const body = new FormData();
  body.set("operation_id", draft.id);
  body.set("note", draft.note);
  if (draft.photo) {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      await draft.photo.arrayBuffer(),
    );
    body.set(
      "photo_sha256",
      Array.from(new Uint8Array(digest), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join(""),
    );
    body.set("photo", draft.photo, "field-photo");
  }
  const response = await api.request(`parcels/${draft.parcel}/field-captures`, {
    method: "POST",
    body,
    signal,
  });
  const receipt = await response.json();
  if (!receipt.id || receipt.parcel_id !== draft.parcel)
    throw new Error(
      "No field capture receipt received. Your capture is still pending.",
    );
}

export async function replayFields(
  api: Api,
  session: FieldSession,
  signal: AbortSignal,
) {
  for (const row of await pending(session)) {
    signal.throwIfAborted();
    if (row.failure) continue;
    try {
      await upload(api, row, signal);
    } catch (err) {
      if (
        err instanceof ApiError &&
        [400, 404, 409, 413, 422].includes(err.status)
      ) {
        await setFailure(session, row.id, err.message);
        continue;
      }
      throw err;
    }
    await removeEntry(session, row.id);
    window.dispatchEvent(new Event("field-synced"));
  }
}
