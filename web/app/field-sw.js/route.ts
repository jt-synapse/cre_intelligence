import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
export const dynamic = "force-static";

const worker = `
const CACHE = "cre-field-shell-__VERSION__";
const ASSETS = ["/field-offline", "/field-store.js"];
self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  await cache.addAll(ASSETS.map(path => new Request(path, {cache: "reload", credentials: "omit"})));
  await self.skipWaiting();
})()));
self.addEventListener("activate", event => event.waitUntil((async () => {
  for (const name of await caches.keys()) {
    if (name.startsWith("cre-field-shell-") && name !== CACHE) await caches.delete(name);
  }
  await self.clients.claim();
})()));
self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || req.headers.has("authorization")) return;
  if (ASSETS.includes(url.pathname) && !url.search) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(url.pathname)).then(hit => hit || fetch(req)));
  } else if (req.mode === "navigate" && url.pathname === "/") {
    event.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.open(CACHE).then(cache => cache.match("/field-offline"))));
  }
});
`;

export async function GET() {
  const hash = createHash("sha256");
  for (const file of ["lib/fieldStore.mjs", "app/field-offline/route.ts"]) {
    hash.update(await readFile(join(process.cwd(), file)));
  }
  return new Response(
    worker.replace("__VERSION__", hash.digest("hex").slice(0, 16)),
    {
      headers: {
        "Content-Type": "text/javascript; charset=utf-8",
        "Service-Worker-Allowed": "/",
        "Cache-Control": "no-cache",
      },
    },
  );
}
