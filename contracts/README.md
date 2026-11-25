# Source provisioning and parcel acceptance

The operator CLI imports local artifacts into a migrated PostgreSQL/PostGIS database. Supply a database credential authorized to register sources and publish data. The API runtime credential has a narrower role. Use private S3-compatible storage in production. Local tests can point `CRE_STORAGE_DIR` at a private directory. Run these commands from the project root with the project Python environment active.

## Source inventory

| Dataset | Source and permitted use |
| --- | --- |
| Gwinnett land parcels, FIPS 13135 | The county's Land Parcels catalog entry identifies a custom license for the recipient's internal use and prohibits sale or distribution. The county guide documents how to download the entire layer or a filtered selection. [Land Parcels item and terms](https://gcgis-gwinnettcountyga.hub.arcgis.com/api/v3/datasets/340cdb68491e49bea5236cecdf66f658_0) · [County download instructions](https://storymaps.arcgis.com/stories/f45dc77d825f4b7a9d7009be78143c29) |
| Gwinnett assessor, FIPS 13135 | The Board of Assessors publishes a quarterly ZIP for download. The internal evaluation uses its ownership and value workbook. The download page provides no express grant for commercial tenant display, redistribution, or automated refresh. [County ownership database](https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database) |
| Gwinnett site address points, FIPS 13135 | The private operator can explicitly include the manually downloaded November 20 snapshot in address lookup. The item permits internal use by the recipient and prohibits distribution or sale. [Site Address Point terms](https://gcgis-gwinnettcountyga.hub.arcgis.com/api/v3/datasets/37205351432348f887d1bef3eb80ddcd_0) |
| Gwinnett Condo Parcel ID, FIPS 13135 | The November 23 private extract covers the 10,446 countywide condo rows and six identity and street fields. The GIS Data Browser terms limit use to the recipient's internal purposes and prohibit distribution or sale. [County condo table](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/10) · [County browser terms](https://www.arcgis.com/sharing/rest/content/items/f6937550eb40432cac62e8c3cf4f3b7b/data?f=json) |
| Gwinnett October plan and occupancy records, FIPS 13135 | The private operator lookup searches the retained county reports and ZIP Portal records. The county portal requires written permission for commercial use. [Development reports](https://www.gwinnettcounty.com/government/departments/planning-development/building-services/development-permits-issued) · [ZIP Portal disclaimer](https://aca-prod.accela.com/GWINNETT/Cap/CapApplyDisclaimer.aspx?TabName=Enforce&module=Enforce) |
| Synthetic parcels and assessor, FIPS 99001 | The demonstration uses fictional Gwinnett-area parcels, permits shared display and export, and has a labeled reference CSV. |

The Land Parcels item `340cdb68491e49bea5236cecdf66f658` points to layer 0 of the Property and Tax service. The parent service item has a blank license field. The county's separate GIS store agreement grants rights on execution, limits use to the licensee, and requires a written addendum for third-party distribution. The county directs users to its open data portal for downloads. [Parent service](https://services3.arcgis.com/RfpmnkSAQleRbndX/ArcGIS/rest/services/Property_and_Tax/FeatureServer) · [County store agreement, §§2, 4 and 5](https://www.gwinnettcounty.com/static/gc/internet/gisstore/GISDataLicenseAgreement.pdf) · [County GIS FAQ](https://www.gwinnettcounty.com/government/departments/information-technology-services/geographic-systems/gis-browser/frequently-asked-questions)

Both Gwinnett contracts allow operator-directed acquisition and private retention for internal evaluation. Shared display and export are disabled. For a customer-facing release, obtain terms covering customer map display, API responses and downloads separately for each source.

## Rehearse the foundation

```sh
alembic upgrade head
python -m cre.ingestion demo --count 1000
python -m cre.ingestion demo --count 1000
python -m cre.ingestion benchmark tests/fixtures/ingestion/synthetic-parcel-labels.csv
python -m cre.ingestion health
python -m cre.ingestion review
```

In an empty database, the first demonstration accepts 1,000 parcels and matches 1,000 assessor rows. Repeating these commands against the same inputs reports `replayed` with the original run IDs. The report carries the publication's counts. A replay creates a separate attempt for audit. The bundled 100-label benchmark exercises 50 addresses and 50 interior points. A 100/100 result establishes the behavior on these synthetic cases. The production benchmark requires separate manually labeled county parcels.

## Import the Gwinnett snapshots privately

Use the operator wrapper from the repository root. It selects the local private database and object directory. Keep the downloaded artifacts in the owner-only `.local/gwinnett-review` directory. The private import records the SHA-256 of each original, the observation date, source locators and the outcomes of validation and matching.

The November 20, 2026 parcel release has 309,555 polygon features. Its GeoJSON explicitly declares EPSG:2240. The source supplies text PINs, tax PINs and GlobalIDs, an integer LRSN and numeric acreage. The importer transforms geometry to WGS84 and checks each feature before publishing. Shared right-of-way labels and ambiguous identifiers are common in this source. Review exceptions before attempting any manual reconciliation. [County feature layer](https://services3.arcgis.com/RfpmnkSAQleRbndX/ArcGIS/rest/services/Property_and_Tax/FeatureServer/0)

The assessor ZIP contains an ownership workbook, a field-layout workbook, and companion files. The ownership workbook PIN joins to the GIS tax PIN. A conflicting LRSN or ambiguous mapping requires review. The primary owner and secondary owner-name line are source text. The workbook's two value totals have separate evidence fields. The county supplies no effective date for this download. The November 22, 2026 observation records the local acquisition date. Its ZIP members carry October 5 file timestamps. [Assessor field mapping](gwinnett_assessor_mapping.md)

Run `setup` to create or reopen the private local database, apply migrations, restrict database access, and register any missing contracts. Import the parcel file before the assessor file. Supply the assessor observation date documented for the source release. Repeating an identical private import with its original date reuses its run. To retry by attempt ID, the CLI reads the private retained object and verifies its digest.

```sh
scripts/gwinnett-internal setup
scripts/gwinnett-internal import gwinnett_parcels .local/gwinnett-review/land-parcels.geojson --as-of 2026-11-20
scripts/gwinnett-internal import gwinnett_assessor .local/gwinnett-review/assessor.zip --as-of 2026-11-22
scripts/gwinnett-internal index-companions
scripts/gwinnett-internal index-situs
scripts/gwinnett-internal verify --require-situs
scripts/gwinnett-internal health
scripts/gwinnett-internal review
scripts/gwinnett-internal retry "$ATTEMPT_ID"
```

The `index-companions` command reads the same retained assessor ZIP. In the two CAMA workbooks it indexes original row numbers, column headers, and the source PIN and land-record number. Both keys must identify the same ownership workbook row to create a link. The two dictionary sheets retain their reference cells. The full source values are available in the original ZIP under each workbook’s recorded SHA-256.

For the November private baseline, `index-situs` reads the ownership workbook’s `PROPERTYSTREET` field and indexes site addresses for accepted ownership-to-parcel links. To look up an address privately, run `scripts/gwinnett-internal lookup-address "$STREET_ADDRESS"` from the project root. Include the full street and any unit. The lookup uses both the assessor site street and the GIS address, trims surrounding spaces and ignores letter case. It returns each distinct active parcel with its matching source citations. Multiple matching parcels remain ambiguous. The owner’s mailing address has a separate purpose.

Use `scripts/gwinnett-internal benchmark-addresses` to exercise the same operator lookup on the frozen labels. Supply the recorded label digest and a new output filename in the private review directory. Add `--address-points` to either private lookup command to scan the complete pinned county Site Address Point snapshot. This option reads the owner-only `address-points/address-points.geojson` and `address-points/catalog.json` under the private review directory. It requires agreement between the point PIN and its covering active parcel. [Benchmark report and replay instructions](gwinnett-internal-import.md#independent-address-benchmark)

Use `--parcel-identities` on either command to include address points and the reviewed condo and held-polygon lookup. This mode also reads the pinned `condo-source/` extract under the private review directory. Each additional result carries a stable private identity, the source of its PIN, the geometry PIN and the role of the cited polygon. A condo identity refers to the shared polygon through a separate parent parcel ID. A held polygon cites the original feature and the open review for its secondary identifier. The lookup runs in a read-only transaction. [Private benchmark](gwinnett-internal-import.md#independent-address-benchmark)

Use the linked private run report for the snapshot dates, publication counts and verification results. An independent accuracy measurement requires hand-labeled addresses or interior points for at least 100 distinct county parcels. The normal Explorer benchmark queries the shared-visibility view, which excludes both private county datasets. [Gwinnett internal import](gwinnett-internal-import.md)

## Recover a standard import and inspect a citation

Every attempt has a UUID, status and observation date. After authorization, the importer retains the original object by SHA-256 and logs its reference. Publication of canonical changes, evidence links and its run record is transactional. A failure leaves the retained input available. Schema drift quarantines the snapshot before canonical publication. Update the source mapping and its version after review, then retry. If missing parcel records subsequently arrive, retry the original assessor attempt to resolve its unmatched rows. Previously accepted claims keep their IDs and the first attempt keeps its original quality report.

The source observation date supplied to `--as-of` is part of snapshot identity. Reordered rows with the same content, mapping and date reuse the original run. The same content on a later observation date produces a new dated citation. Importing an older observation preserves the newer current geometry. Upgrading from an earlier schema lists previously misdated replays in `python -m cre.ingestion review`. Retry the listed `attempt_id` to publish the retained snapshot for its original date under the current source permissions.

```sh
python -m cre.ingestion retry "$ATTEMPT_ID"
```

The Explorer's visible-source views expose the publisher, original source origin, current attribution, record digest, snapshot run, and dataset key. The claim locator identifies the original feature or workbook sheet, row and field. An assessor's listed owner is a source-specific claim. Registry identity, beneficial ownership, or a professional contact route requires separate evidence.

Re-registering the same dataset with `rights.status=disabled` removes its parcels and claims from the shared views. Clearing only `export_allowed` retains permitted in-app display. Approved extraction, storage, in-app display and dossier export are separate decisions. Keep the original permissions and the updated decision in the source registry's manifest history.
