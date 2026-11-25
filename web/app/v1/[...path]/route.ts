import { copyRequestHeaders, upstreamURL } from "../../../lib/proxy.mjs";

export const dynamic = "force-dynamic";

async function proxy(
  request: Request,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  let url: string;
  try {
    url = upstreamURL(
      process.env.CRE_API_URL || "http://127.0.0.1:8000",
      path,
      new URL(request.url).search,
    );
  } catch {
    return Response.json({ detail: "Invalid resource path" }, { status: 400 });
  }
  const options: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers: copyRequestHeaders(request.headers),
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };
  if (request.body && request.method !== "GET" && request.method !== "HEAD") {
    options.body = request.body;
    options.duplex = "half";
  }
  try {
    const response = await fetch(url, options);
    if (response.status >= 300 && response.status < 400)
      return Response.json(
        { detail: "Unexpected API redirect" },
        { status: 502 },
      );
    const headers = new Headers({
      "cache-control": "private, no-store",
      "x-content-type-options": "nosniff",
    });
    for (const key of [
      "content-type",
      "content-disposition",
      "retry-after",
      "www-authenticate",
    ]) {
      const value = response.headers.get(key);
      if (value) headers.set(key, value);
    }
    return new Response(response.body, { headers, status: response.status });
  } catch {
    return Response.json(
      { detail: "The API is unavailable." },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as DELETE,
  proxy as PUT,
};
