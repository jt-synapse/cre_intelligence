# Production pilot deployment and acceptance

## Provision and configure

1. Provision a private managed PostgreSQL database with PostGIS, btree_gist and pg_trgm available. Use TLS with certificate verification. Give the migration role schema ownership and the ability to install the extensions, or have the database operator preinstall them. Create separate API and worker login roles with NOSUPERUSER and NOBYPASSRLS and no membership in the owner role. The API receives only its runtime URL. The worker receives only its worker URL. A backup operator requires read access across tenants and a separate credential.
2. Provision a private, encrypted, versioned S3-compatible bucket. Block public access. Grant the runtime identities access to necessary object operations under the objects prefix. Use scoped workload identity where available. Enforce provider retention and deletion rules before registering a source. Separate staging and production buckets and database credentials.
3. Register a public OIDC authorization-code client with PKCE and an exact HTTPS callback at the web origin under /auth/callback. Configure the API issuer, JWKS URL and access-token audience. Use the migration credential with `python -m cre.admin member --org UUID --name NAME --subject OIDC_SUB --role researcher` to provision a membership. Assign shared curation only to designated reviewers using `--curator`. Keep demo authentication disabled. Serve the web application through an HTTPS ingress. Restrict the private API to the web proxy and operators.
4. Set the variables in `compose.pilot.yaml` through the deployment environment or its secret store. Set `CRE_RELEASE` to an immutable release identifier. Configure a basemap only with permitted attribution and display rights. Set worker request and token budgets and approved model pricing when enabling paid research.
5. Build the Python and web images, back up the database and object versions, and run the one-shot `migrate` service. It upgrades Alembic and applies separate runtime/worker grants. Register only approved sources. Deploy API, worker and web. Probe /health/live and /health/ready and sign in through the real issuer before directing pilot users to the release.

The reference Compose deployment binds only the web origin on host loopback. Supply a TLS reverse proxy on the target or translate the services into your managed runtime. Keep credential values in the secret manager. Avoid printing expanded Compose configuration when it contains credentials.

## Operate and recover

- Collect API request duration, route, response status and request ID from the service logs. Track p95 for the cached property detail route. To reproduce the latency measurement, set a scoped access token in `CRE_BENCHMARK_TOKEN` and run `scripts/benchmark-profile HTTPS_ORIGIN PROPERTY_UUID`. The command warms the endpoint five times before timing 100 authenticated requests. Export periodic `python -m cre.maintenance health` results from the operator account to the platform monitor. It reports source freshness and quality, queued/failed work and provider usage. Alert on missed scheduled imports, mapping changes, failed jobs, rising queue age and unexpected provider spend. Set cost thresholds with the pilot sponsor.
- Inspect individual input failures using `python -m cre.ingestion health` and `review`. Disable the source or restrict its export manifest when permissions change. Fix mapping drift on the retained artifact, then use `retry ATTEMPT_ID` or publish the corrected mapping version. Inspect failed research/report jobs through the admin jobs API and record the reason for retry.
- Enable managed point-in-time database recovery and independently backed-up object versions. During release rehearsal, restore into an isolated database and bucket or object directory, configure a verifier with tenant-wide backup read permissions, and run `python -m cre.maintenance verify-restore`. It reads all referenced artifacts, checks their content hashes, validates spatial and claim integrity, and reconstructs published PDFs from pinned snapshots. Test downloading a report and reopening its accessible evidence with the runtime role.
- For the local rehearsal, run `scripts/restore-drill` after publishing a demonstration report. It creates a new database, a database dump and a separately copied object directory, and prints the paths. In the managed environment, revert a failed application deployment to its previous image while retaining compatible migrations. Restore backups to a new environment for a rollback that requires database recovery.

## Evidence for releasing Gwinnett

| Gate | Evidence to collect from the pilot |
| --- | --- |
| County data | Approved parcel and separately mapped assessor snapshots, rights decisions, reproducible import IDs and quality summaries. Independently reviewed set of 100 parcels with at least 98 correct matches. |
| Ownership and contacts | 30 LLC and 30 business contact cases, 100 document samples, all material claims cited, and zero incorrect automatic entity or personal-contact verifications. Include a documented representative, opaque ownership, conflicting sources and inaccessible records. |
| Operations and finance | 50 opportunities across workspace roles, all 25 deterministic financial fixtures passing, a completed task workflow and a reviewed downloadable dossier. |
| Runtime | A cached property detail p95 below one second on the pilot dataset, all tenant-isolation tests passing, and a successful staging database/object restore with reconstructible reports. |
| User acceptance | Pilot users complete discovery, LLC investigation, opportunity evaluation, team operations and cited export. Record actual case outcomes, cost and release decision. |

Synthetic benchmarks exercise software behavior. Record genuine county accuracy and real user outcomes separately. Fulton County follows the Gwinnett acceptance decision.
