/** Construct a fixed-origin URL from validated, decoded Next route segments. */
export function upstreamURL(base, segments, search) {
  if (
    !segments.length ||
    segments.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part))
  )
    throw new Error("Invalid API path");
  const url = new URL("/v1/" + segments.join("/"), base);
  url.search = search;
  return url.toString();
}
export function isLoopback(hostname) {
  return ["localhost", "127.0.0.1", "[::1]"].includes(hostname);
}
export function copyRequestHeaders(headers) {
  const safe = new Headers();
  for (const key of [
    "authorization",
    "x-organization-id",
    "content-type",
    "accept",
  ]) {
    const value = headers.get(key);
    if (value) safe.set(key, value);
  }
  return safe;
}

/** Source records can also identify private objects or local files. Only web links are navigable. */
export function publicSourceURL(value) {
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}
