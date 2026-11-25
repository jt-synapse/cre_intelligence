import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const dynamic = "force-static";

export async function GET() {
  return new Response(
    await readFile(join(process.cwd(), "lib/fieldStore.mjs"), "utf8"),
    {
      headers: {
        "Content-Type": "text/javascript; charset=utf-8",
        "Cache-Control": "no-cache",
      },
    },
  );
}
