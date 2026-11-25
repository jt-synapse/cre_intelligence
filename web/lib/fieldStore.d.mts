export type FieldSession = {
  nonce: string;
  org: string;
  subject: string;
  writable: boolean;
  expires: number;
};
export type FieldDraft = {
  id: string;
  parcel: string;
  note: string;
  photo: File | null;
  failure?: string;
  size: number;
  created: number;
};
export function currentSession(): FieldSession | null;
export function bindSession(
  org: string,
  subject: string,
  writable: boolean,
  grantHours?: number,
): Promise<FieldSession>;
export function clearSession(): Promise<void>;
export function pending(session: FieldSession): Promise<FieldDraft[]>;
export function removeEntry(session: FieldSession, id: string): Promise<void>;
export function enqueue(
  session: FieldSession,
  parcel: string,
  note: string,
  photo: File | null,
): Promise<FieldDraft>;
export function rememberParcel(session: FieldSession, parcel: string): void;
export function lastParcel(session: FieldSession): string | null;
export function listen(
  kind: "field-session-change" | "field-queue-change",
  handler: () => void,
): () => void;

export function renewSession(session: FieldSession): Promise<FieldSession>;
export function suspendSession(session: FieldSession): Promise<void>;
export function pendingCount(session: FieldSession): Promise<number>;

export function setFailure(
  session: FieldSession,
  id: string,
  reason: string | null,
): Promise<void>;
