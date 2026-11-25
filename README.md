# CRE Intelligence

A parcel-first research workspace for commercial real estate. Search a parcel, inspect its cited observations, save a provisional property, review ownership and contact evidence, and carry the same property into a portfolio, opportunity, financial scenario, or reviewed PDF dossier.

## Run the local demonstration

Use Docker with Compose, Python 3.12, uv and Node.js 24. From this directory:

```sh
uv sync --frozen --python 3.12 --extra test
npm ci --prefix web
scripts/local setup
```

Run these commands in separate terminals:

```sh
scripts/local api
scripts/local worker
scripts/local web
```

Open [the workspace](http://127.0.0.1:3000), choose **Open local demo**, and search for **100 Example Commerce Dr**. Select the parcel, inspect the sources, and save it. The workspace seeds six fictional parcels and their assessor rows in demonstration jurisdiction 99001. Demo mode is explicit and local services bind to loopback. [API explorer](http://127.0.0.1:8000/docs)

The API writes workspace data through a restricted PostgreSQL login. A separate worker processes investigations and reports. Source manifests and evidence determine which records users can see and export. An organization admin can manage portfolio activity. A global curator privilege is additionally required for shared property grouping and shared claim review.

## Phone field workflow

Open the local demo and search for **100 Example Commerce Dr**. On a phone-sized screen, selecting a parcel opens its boundary date and assessor-listed owner. **Open full record** shows the cited observations. **Locate me** requests device location. If search finds multiple parcels at a boundary, choose the intended parcel from the list. Use **Measure** to draw an approximate length or area.

Under **Field captures**, save a note or a JPEG, PNG or WebP photo. The pending entry survives an offline reload of the same signed-in tab. Reconnecting revalidates workspace membership and retries with the same operation ID. The offline shell retains pending captures and the last selected parcel ID. Maps, ownership records and reports require connectivity. The workspace administrator can view the offline grant duration in the header. Set `CRE_FIELD_GRANT_HOURS` on the web service to choose 1–12 hours (default 12).

Use **Saved field places** to organize pins and record a visit. In **Field sites**, add the selected parcels, preview their combined footprint, and save a named revision. Each member retains its boundary and source version. Source permissions are checked again when a saved site opens.

The loopback demo is available on the development Mac. A physical handset requires a reachable HTTPS deployment with an authorized sign-in and permitted demonstration data.

## Data provisioning

The Gwinnett land-parcel and assessor contracts allow a manual import into a private internal evaluation. Use `scripts/gwinnett-internal` for those inputs. Shared display, customer exports and scheduled acquisition are disabled. The source guide explains the permissions, import commands and verification steps. [Source provisioning guide](contracts/README.md)

Import a permitted zoning, flood or environmental layer with `python -m cre.screening import MANIFEST.json SOURCE.geojson` using the operator credential. Its manifest supplies the dataset key, kind, observed date, reference, rights reference, authorization for manual import and retention, shared display and export flags, and the label field. Supply a WGS84 coverage polygon when the source documents its footprint. The Explorer reports a completed screen with no match only for parcels inside that documented coverage. Use `python -m cre.screening disable DATASET_KEY` to withdraw it.

## Verification

```sh
scripts/local-test-db -q
npm --prefix web test
npm --prefix web run build
npm --prefix web run typecheck
```

The database suite creates separate disposable PostGIS databases for Explorer, ingestion, and workflow tests. For the S3 adapter test, run `docker compose -f infrastructure/compose.storage-test.yaml up -d --wait` and set `CRE_TEST_S3_ENDPOINT=http://127.0.0.1:59009` when invoking the suite. With the seeded app, API, and worker running, use `CRE_WEB_TEST_URL=http://127.0.0.1:3000 npm --prefix web run test:browser` after installing the Playwright Chromium browser. For an isolated end-to-end rehearsal, `npm --prefix web run test:pilot` provisions its own database and processes. CI repeats the database, web build, and browser checks.

To exercise a paid model, set `CRE_RESEARCH_PROVIDER=openai` and an authorized `CRE_OPENAI_MODEL` on the **worker**. The local worker loads the approved project key from the ignored `.env.local` only in this mode. Each case has its own request and token budgets, and each document must permit AI processing. The local demo and CI operate with model calls disabled by default. `scripts/model-smoke` performs one live request against a fictional excerpt when invoked explicitly with a model selected.

## Production pilot

The service images and portable deployment definition target managed PostGIS, private object storage and an OIDC issuer. The runbook covers source permissions, credentials, upgrades, monitoring, restore verification and the acceptance evidence required before opening a pilot. [Deployment and qualification](infrastructure/PILOT.md)
