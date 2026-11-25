// This response contains only static presentation and field-queue code.
// The limited offline grant stays in the authenticated browser tab.
export const dynamic = "force-static";
const html = `<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline fieldwork · CRE Intelligence</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5ef;color:#183c31;font:1rem/1.5 system-ui,sans-serif}
main{max-width:40rem;margin:auto;padding:1.5rem}h1,h2{font-family:Georgia,serif}
label{display:grid;gap:.3rem;margin:.7rem 0}textarea,input,button{font:inherit;max-width:100%}
textarea{min-height:5rem;padding:.6rem}button{border:0;border-radius:.35rem;background:#245843;color:white;padding:.65rem .9rem}
li{background:white;margin:.5rem 0;padding:.75rem;overflow-wrap:anywhere}ul{padding:0;list-style:none}
img{display:block;max-width:100%;max-height:12rem;margin-top:.5rem}a{color:inherit}small{display:block}
</style></head><body><main><p>CRE Intelligence</p><h1>Offline fieldwork</h1>
<p role="status" id="status">Opening field drafts…</p><section hidden id="drafts"><h2>Pending captures</h2>
<ul id="list"></ul></section>
<form id="capture" hidden><h2>Add a capture</h2><p id="destination"></p>
<label>Field note<textarea name="note" maxlength="4000"></textarea></label>
<label>Field photo<input type="file" name="photo" accept="image/jpeg,image/png,image/webp" capture="environment"></label>
<button>Save field capture</button></form>
<p><a href="/">Return to workspace</a></p></main>
<script type="module">
import { currentSession, pending, lastParcel, enqueue, listen } from "/field-store.js";
const get = id => document.getElementById(id);
let generation = 0, urls = [], expiry;
function clean() {
  get("list").replaceChildren();
  urls.forEach(URL.revokeObjectURL); urls = [];
  get("drafts").hidden = get("capture").hidden = true;
}
async function refresh() {
  const version = ++generation, grant = currentSession();
  clean(); clearTimeout(expiry);
  try {
    const rows = await pending(grant);
    if (version !== generation) return;
    expiry = setTimeout(refresh, Math.max(1, grant.expires - Date.now()));
    get("drafts").hidden = false;
    get("status").textContent = rows.length ? "Pending captures will sync after you reconnect." : "No captures waiting to sync.";
    for (const row of rows) {
      const li = document.createElement("li");
      li.textContent = row.note;
      const parcel = document.createElement("small");
      parcel.textContent = "Parcel " + row.parcel;
      li.append(parcel);
      if (row.photo) {
        const img = document.createElement("img");
        img.alt = "Pending field photo"; img.src = URL.createObjectURL(row.photo);
        urls.push(img.src); li.append(img);
      }
      get("list").append(li);
    }
    const parcel = lastParcel(grant);
    get("capture").hidden = !(parcel && grant.writable);
    get("destination").textContent = parcel ? "Selected parcel " + parcel : "";
  } catch (error) {
    if (version !== generation) return;
    get("capture").reset();
    get("status").textContent = error.message;
  }
}
get("capture").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, grant = currentSession();
  form.querySelector("button").disabled = true;
  try {
    await enqueue(grant, lastParcel(grant), form.elements.note.value, form.elements.photo.files[0] || null);
    form.reset(); await refresh();
  } catch (error) { get("status").textContent = error.message; }
  finally { form.querySelector("button").disabled = false; }
});
listen("field-session-change", refresh);
listen("field-queue-change", refresh);
addEventListener("pageshow", refresh);
addEventListener("pagehide", clean);
addEventListener("online", () => location.replace("/"));
refresh();
</script></body></html>`;
export function GET() {
  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-cache",
    },
  });
}
