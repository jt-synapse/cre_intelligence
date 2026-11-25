export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export type Api = ReturnType<typeof client>;
export function client(token: string, org?: string) {
  async function request(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    headers.set("Authorization", "Bearer " + token);
    if (org) headers.set("X-Organization-ID", org);
    const response = await fetch("/v1/" + path, {
      ...init,
      headers,
      cache: "no-store",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((x: { msg: string }) => x.msg).join(". ")
            : "Request failed";
      throw new ApiError(
        response.status,
        response.status === 401
          ? "Your session has expired. Sign in again."
          : detail,
      );
    }
    return response;
  }
  async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return (await request(path, { signal })).json();
  }
  async function send<T>(
    path: string,
    data: unknown,
    method = "POST",
  ): Promise<T> {
    const form = data instanceof FormData;
    const response = await request(path, {
      method,
      headers: form ? {} : { "Content-Type": "application/json" },
      body: form ? data : JSON.stringify(data),
    });
    return response.status === 204 ? (undefined as T) : response.json();
  }
  return { get, send, request };
}
export function message(err: unknown) {
  return err instanceof Error
    ? err.message
    : "Unable to complete this request.";
}
export function rows<T>(value: T[] | { items: T[] }): T[] {
  return Array.isArray(value) ? value : value.items;
}
