import { readFile } from "node:fs/promises";
import { join } from "node:path";

// Keep the worker on the application origin. The browser bundle and worker come
// from the same locked MapLibre installation, including deployments without a CDN.
export const dynamic = "force-static";
export async function GET() {
  const bundle = await readFile(
    join(process.cwd(), "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"),
  );
  return new Response(new Uint8Array(bundle), {
    headers: {
      "Content-Type": "text/javascript;charset=utf-8",
      "Cache-Control": "public, max-age=0, must-revalidate",
    },
  });
}
