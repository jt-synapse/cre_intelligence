# Gwinnett private import report

On November 23, 2026, the private Gwinnett database accounted for every row in both county snapshots. The assessor import linked 303,186 assessor-listed ownership records to distinct parcels. The remaining 12,157 assessor rows went to review. Both datasets are restricted to manual, private evaluation. [Source permissions](README.md#source-inventory)

## Published snapshots

| Source | Observed on | Input rows | Accepted | Held for review | Publication run ID |
| --- | --- | ---: | ---: | ---: | --- |
| Land parcels | 2026-11-20 | 309,555 | 305,161 | 4,394 | `5332efd6-1c38-4e94-b18d-ef721696393b` |
| Assessor ownership workbook | 2026-11-22 | 315,343 | 303,186 | 12,157 | `9ff3ed30-2947-4ec9-9371-8662814df950` |

The parcel observation uses the county layer’s last data edit. The assessor observation uses the November 22 local download date. The ownership workbook was last saved October 5, 2026. The county supplied no effective date for the complete ownership roll. [Assessor field mapping](gwinnett_assessor_mapping.md)

## Permitted use and workbook mapping

Gwinnett County GIS limits the parcel export to the recipient’s internal use and prohibits distribution or sale. [County parcel terms](https://gcgis-gwinnettcountyga.hub.arcgis.com/api/v3/datasets/340cdb68491e49bea5236cecdf66f658_0)

The county invites users to download and save the quarterly assessor ZIP. The operator treated a private working copy and structured inspection as implied by that invitation. The page grants no express right to publish a commercial customer product. Both source contracts disable shared display, customer export and automatic acquisition. [County assessor download](https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database)

The ownership workbook’s `PIN` matches GIS `TAXPIN`. Matching against GIS `PIN` yielded zero overlaps. The importer checks `LRSNum` against GIS `LRSN` when available and holds conflicting keys for review. `OWNERNAME1` supplies the assessor-listed owner. The second name line and both value totals retain their original source meanings. [Workbook mapping and crosswalk](gwinnett_assessor_mapping.md)

## Companion workbooks

The private index covers all 632,531 CAMA source lines. Each entry records its workbook, original Excel row, and the two county keys. A link requires exact agreement with one original ownership workbook row. An ownership row can have multiple improvement or land lines and can itself be held from the GIS join. The full attribute values remain in the retained workbook. [Workbook inventory and member digests](gwinnett_assessor_mapping.md#archive-inventory)

| Sheet | Source lines indexed | Linked to ownership workbook | Without an exact key pair |
| --- | ---: | ---: | ---: |
| Improvements | 308,830 | 305,803 | 3,027 |
| Land | 323,701 | 315,343 | 8,358 |

The property class dictionary contributes 284 reference rows and the tax digest layout contributes 42. Their original field values, headings, and worksheet positions are available in the private index.

## Recovery record

The original assessor attempt `9e3e9ead-7ca1-4a3f-b8e4-db1248a47d34` had retained its input and was still marked `staging`. The process check found no importer, and the database had no other session or committed assessor run. The cause of the interruption is unknown.

The operator retried that attempt with `scripts/gwinnett-internal retry` using the retained ZIP and original observation date. Recovery attempt `477e78fb-76ae-4dad-b2ef-a0a6803cb622` published the assessor run above. The operator then closed the original attempt as `failed` and recorded the successful retry ID in its audit entry.

Replaying the two original files through the normal private import command returned the same two publication IDs and counts. The replay attempts were `ac002c86-995a-4a72-8a6e-1d403378771a` for GIS and `3139ba00-7b2f-4220-af10-01c78a9ccf0c` for ownership.

The retained objects matched the expected SHA-256 digests.

| Object | SHA-256 |
| --- | --- |
| Parcel GeoJSON | `7bc547068cfaea1d884f9819bc304dabb79872f9d5c254185753561d5b4222e0` |
| Assessor ZIP | `e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca` |

## Rows held for review

All counts below were unresolved at verification.

| Source | Reason | Rows |
| --- | --- | ---: |
| Assessor | No matching GIS tax parcel ID (TAXPIN) | 12,139 |
| Assessor | No matching TAXPIN, with only the secondary identifier (LRSNum) available as a match | 3 |
| Assessor | LRSNum disagreed with the parcel selected by TAXPIN | 12 |
| Assessor | TAXPIN and LRSNum identified different GIS parcels | 3 |
| Land parcels | Colliding source identifiers | 4,351 |
| Land parcels | Invalid geometry | 43 |

## Verification

`scripts/gwinnett-internal verify` exited successfully for the parcel and ownership baseline and the companion index. [Verification SQL](gwinnett-internal-check.sql)

- Every input position was present. Each source row produced exactly one accepted result or one review item.
- All 3,063,073 claims had exactly one supporting source record and passed the source-field, locator, and observation-date checks.
- All 303,186 ownership links passed. The verifier found zero broken links, ambiguous links, links to held rows, or repeated parcels.
- All 305,161 parcel geometries passed the geometry and county-envelope checks. All 308 sampled interior points fell within their corresponding geometries.
- A direct comparison with the retained files checked 23 parcel features and 23 ownership rows. All 46 source record hashes, 240 field values and field citations, and 23 transformed geometries matched.
- All 632,857 companion worksheet positions were accounted for. The check confirmed 621,146 links to original ownership records and the widths of both dictionaries. Replaying the index preserved all counts.
- The private database denied connection to the application, worker, and public roles. Shared views exposed zero county source records, parcels, or claims.

## Independent address benchmark

### Completed October plan and occupancy listings

**November 23, 2026 — 94 of 100 correct, six unresolved, zero wrong or ambiguous.** The private lookup now includes 347 additional listings. A replay on the frozen November permit sample returned the same parcel candidates for all 100 addresses. The pilot requires 98 correct and human review of the labels remains open.

The two public searches covered the full month by listing date. Collection used only the date range and record class. The October 8–31 result pages contained 399 distinct records, including 52 already in the first collection. Each retained page was checked against its date range, record class and position in the result set. Counts reconciled to the portal for each period. [County commercial permit search](https://aca-prod.accela.com/GWINNETT/Cap/CapHome.aspx?module=PlanReview&TabName=PlanReview)

| October dates | Complete-project plans | Business-license occupancy applications |
| --- | ---: | ---: |
| 1–7 | 74 | 60 |
| 8–14 | 60 | 61 |
| 15–21 | 75 | 58 |
| 22–28 | 51 | 58 |
| 29–31 | 18 | 18 |
| **Month** | **278** | **255** |

Together with the 37 development records, the private index contains 570 records. Ten listings matched the full addresses of five benchmark cases. Four of those cases already had the correct parcel. For the fifth, **4405 International Boulevard**, the October 26 application shows “Plans Authorized” and gives the street address. The grid omits the parcel ID and the date of authorization. Fifteen county address points at the street address span two parcel IDs. The lookup kept the case open.

The Satellite Boulevard listing includes Building 400 and omits Suite 104. The North Brown Road listing omits Suite 175. The lookup still needs the full building or suite designation, dated source evidence and geographic corroboration before either association can count. The Mall of Georgia conflict also remains open.

The private release under `.local/gwinnett-review/october-completion/` contains the original result pages, coverage by date, the supplemental index, and the benchmark report in `score.json`. A separate parser reconstructed all 347 new listings from the pages and verified the document hits, parcel candidates and outcomes for every case. Verify the release and rerun the lookup with these commands.

```sh
collection=.local/gwinnett-review/october-completion
labels=.local/gwinnett-review/parcel-benchmark-2026-11-23/frozen-labels.csv
.venv/bin/python "$collection/freeze.py" --verify
.venv/bin/python "$collection/audit.py"
replay_dir=$(mktemp -d "$collection/replay.XXXXXXXX")
scripts/gwinnett-internal benchmark-addresses "$labels" \
  --sha256 517a51c418c02fe9e097c5dbb78a1ffbb448024033bf58b4e44adc73806bc1f3 \
  --plan-occupancy --output "$replay_dir/score.json"
```

#### Solar permit at 4405 International Boulevard

The county linked plan `EPN2026-03019` to building permit `COMBLD2026-02593`. Both name parcel **6201 114** for the rooftop solar project. The plan entered the October listings on October 26. The Plans Coordination history records pending payment on November 9 and authorization on **November 13, 2026**, the same day the county issued the building permit. The benchmark evidence cutoff was November 8. [County plan and processing history](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=PlanReview&TabName=PlanReview&capID1=26CAP&capID2=00000&capID3=0079L&agencyCode=GWINNETT) · [County building permit and issued PDF](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=Building&capID1=26BLD&capID2=00000&capID3=09098&agencyCode=GWINNETT)

The October 28 structural engineer’s letter gives the street address. The issued permit also gives the street address and leaves the shell building number blank. The county site plan appeared in the attachment list without a public download link. The evidence for Building A comes from its primary county address point, which lies inside the original polygon for 6201 114. Buildings B and C have primary points inside the neighboring polygon for 6201 032. This confirms the project's parcel for manual review. The address-only case remains unresolved and the frozen benchmark stands at 94 of 100. The private evidence and verification script are in `.local/gwinnett-review/international-blvd-review/`. [County site address points](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/0)

### Initial October plan and occupancy collection

**November 23, 2026 — 94 correct of 100.** The private address lookup returned the same 94 parcel IDs as the preceding run and left six cases unresolved. There were zero wrong or ambiguous results. The pilot requires 98 correct, and human label sign-off remains open. All 100 inputs and reference parcel IDs came from the existing frozen November 9–13 county permit sample.

The selection used October submission or issuance dates across the county's planning department. It excluded searches by benchmark address, parcel ID or permit number. The private index contains 223 records. One plan listing matched the complete address of an already-correct case. None of the six unresolved full addresses appeared. The conflicting Mall of Georgia suite assignment remains open.

| October source | Retained | Evidence and coverage |
| --- | ---: | --- |
| Complete-project plan applications | 86 | All 74 results for October 1–7, ten of 60 for October 8–14 and two from October 30. Nineteen showed “Plans Authorized” at retrieval. The listings omit the parcel ID and authorization date. [County commercial plan search](https://aca-prod.accela.com/GWINNETT/Cap/CapHome.aspx?module=PlanReview&TabName=PlanReview) |
| Occupancy applications for a business license | 100 | All 60 results for October 1–7, thirty of 61 for October 8–14 and ten from October 30–31. Thirty-two showed “CO Issued.” No retained record established both a parcel ID and certificate issuance by November 8. [County occupancy application guide](https://www.gwinnettcounty.com/static/upload/pnd/Guidance/284/certificate_of_occupancy_no_construction_instructions.pdf) |
| Development cases issued or approved | 37 | All 37 October cases by printed issue date in five weekly reports. Thirteen plats had a dated authorization and parcel ID. Twenty-four development permits had an issued permit. The separate five weekly building-permit reports accounted for 749 October permits and contained zero explicitly classified occupancy certificates. [Development reports](https://www.gwinnettcounty.com/government/departments/planning-development/building-services/development-permits-issued) · [Building reports](https://www.gwinnettcounty.com/government/departments/planning-development/building-services/building-permits-issued) |

The county portal rate-limited access during collection. Coverage after October 7 is partial for both portal searches. The records include dated public reports, retained portal result pages and field transcriptions for 84 plan listings. The source manifests distinguish these evidence types. Missing dates, application status and block-level addresses remain visible to operators.

The operator can search a full street and suite with `scripts/gwinnett-internal lookup-address "$STREET_ADDRESS" --plan-occupancy`. A new parcel prediction requires qualifying dated documentary evidence and independent geographic corroboration. The county site points must agree on one PIN, and at least one primary point must have unique, agreeing polygon coverage. A competing covered parcel holds the result for review. Building identifiers, suite identifiers and their suffixes are preserved. [Private document lookup](../cre/ingestion/gwinnett_plan_occupancy.py)

An independent replay from the retained records reproduced all 100 candidate sets and outcomes. A separate single-address lookup outside the sample returned one parcel and cited both its primary address point and an authorized October plat. The private score is `.local/gwinnett-review/plan-occupancy-collection/score-plan-occupancy-v2.json` (SHA-256 `f9f0ba3389b3a657c6cab3cdd39f4530caa2a60c433bf4e3b75921b6c1132eef`). Its case-by-case comparison is in `independent/operator-comparison-v2.json` under the same directory. The following commands verify the original collection and score the latest installed release.

```sh
collection=.local/gwinnett-review/plan-occupancy-collection
labels=.local/gwinnett-review/parcel-benchmark-2026-11-23/frozen-labels.csv
.venv/bin/python "$collection/freeze_collection.py" --verify
replay_dir=$(mktemp -d "$collection/replay.XXXXXXXX")
scripts/gwinnett-internal benchmark-addresses "$labels" \
  --sha256 517a51c418c02fe9e097c5dbb78a1ffbb448024033bf58b4e44adc73806bc1f3 \
  --plan-occupancy --output "$replay_dir/score.json"
```

### Private lookup with reviewed parcel identities

**November 23, 2026 — 94 of 100 correct, four short of the pilot requirement.** On the frozen sample the private lookup returned 94 unique correct parcel IDs and six cases with no match. All 92 earlier matches retained the same candidates. The two additional identifications use countywide records and rules derived while investigating this sample. A fresh blinded sample would measure performance beyond these permit cases. Human sign-off on the labels remains open.

| Newly matched identity | Evidence used by the lookup |
| --- | --- |
| Condominium unit on a shared polygon | The county's 10,446-row condo table names the unit, tax PIN, site street, land-record number and common parcel. The assessor confirms the tax keys and street. The unit's primary condo point lies strictly inside the single common polygon in the original export and the active publication. The result returns the unit PIN and separately cites the parent geometry shared by 98 units. [County condo table](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/10) |
| Polygon held for a conflicting secondary identifier | The original GIS feature has a unique PIN, tax PIN and GlobalID. Its tax PIN links to an exact assessor site street. A primary building point names that parcel and lies strictly inside its polygon. Seven GIS features share the secondary identifier. The private result cites the original feature and the open review. [Held parcel lookup](../cre/ingestion/gwinnett_held_identity.py) |

The independent raw-file replay checked all 100 candidate sets against the underlying sources. Outside the sample, two additional condo addresses returned distinct unit IDs on one common polygon. Three addresses shared by multiple condo units returned two, four and eleven candidates respectively. These checks are separate from the benchmark.

Six permit addresses returned no match. Four contain suite or building identifiers beyond the lookup's indexed sources. One lacks a corroborated house number, and one needs a building designation to distinguish between two parcels at the same street address.

#### Review of the four commercial suites

On November 23, 2026, the operator followed each issued permit to its separate county plan-review record. All four plan records showed **Plans Authorized**. Three agreed with their issued permit on the suite and parcel. These records were found using the four known permit IDs; counting them as automatic address matches would overstate the result. A fresh run of the address-only lookup reproduced all 100 prior case results, including 94 correct matches.

| Site | What the public record establishes |
| --- | --- |
| Satellite Boulevard | The authorized plan names Building 400, Suite 104 and parcel `6206 060`. The county also records **CO Issued** for an earlier tenant at Suite 104 on that parcel. The historical permit report supplies the complete building and suite on page 13. [Authorized plan](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=PlanReview&TabName=PlanReview&capID1=26CAP&capID2=00000&capID3=006RG&agencyCode=GWINNETT) · [Prior occupancy record](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=Building&TabName=Building&capID1=17BLD&capID2=00000&capID3=02243&agencyCode=GWINNETT) |
| North Brown Road | The authorized plan and issued permit both assign Suite 175 to parcel `7114 162`. [Authorized plan](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=PlanReview&TabName=PlanReview&capID1=26CAP&capID2=00000&capID3=006PE&agencyCode=GWINNETT) |
| Oakbrook Parkway | The tenant's signed October 28 water-resources form gives Building 100 and Suite 100 in separate fields. The authorized plan assigns Suite 100 to parcel `6197 026`. The issued permit prints the complete address as `100 - 100` on that parcel. [Authorized plan and attachments](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=PlanReview&TabName=PlanReview&capID1=26CAP&capID2=00000&capID3=006H6&agencyCode=GWINNETT) |
| Mall of Georgia | The authorized plan identifies Suite 2033-A on parcel `7176 004`. The issued permit gives exactly the same suite on parcel `7176 034`. The parcel assignment remains unresolved. [Authorized plan](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=PlanReview&TabName=PlanReview&capID1=26CAP&capID2=00000&capID3=0056H&agencyCode=GWINNETT) · [Issued permit](https://aca-prod.accela.com/GWINNETT/Cap/CapDetail.aspx?Module=Building&TabName=Building&capID1=26BLD&capID2=00000&capID3=06504&agencyCode=GWINNETT) |

The private audit at `.local/gwinnett-review/occupancy-review/verified-case-review.json` records the URLs, source hashes, prior-tenant occupancy status and score replay. The original frozen labels remain the reference. An address-searchable collection of plan or occupancy records selected independently of the misses could test the three corroborated associations through the normal operator lookup.

The private result is `.local/gwinnett-review/parcel-benchmark-2026-11-23/score-parcel-identities-v1.json` (SHA-256 `cdd88f0a9caf7e5e0f47c5082fa019663b10f0dbc365b6fe75be8a7a6ac9c4d3`). The same directory contains the independent verifier in `identity-independent/` and its per-case comparison in `identity-independent/final-comparison.json`. The condo acquisition receipt and original pages are in `.local/gwinnett-review/condo-source/`.

To repeat the private lookup, run the following command from the project root. Use `lookup-address "$STREET_ADDRESS" --parcel-identities` through the same wrapper for an individual address. Each result records the identity and geometry sources, including the original review on a held polygon. This mode requires the retained county snapshots and reads the local database in a read-only transaction.

```sh
bundle=.local/gwinnett-review/parcel-benchmark-2026-11-23
replay_dir=$(mktemp -d "$bundle/replay.XXXXXXXX")
scripts/gwinnett-internal benchmark-addresses "$bundle/frozen-labels.csv" \
  --sha256 517a51c418c02fe9e097c5dbb78a1ffbb448024033bf58b4e44adc73806bc1f3 \
  --parcel-identities --output "$replay_dir/score.json"
```

### Historical private evaluation with county address points

**November 23, 2026 — 92 of 100 correct, six short of the pilot requirement.** The same 100 permit addresses produced 92 unique correct parcels and eight with no qualifying candidate. There were zero wrong unique or ambiguous lookup results. An independent scan of the original GIS polygons, assessor workbook and address points reproduced all 100 outcomes. Human sign-off on the labels remains open. The sample covers one week of permit activity. [Pilot criteria](../infrastructure/PILOT.md#evidence-for-releasing-gwinnett)

Five of the six gains over the assessor result came from the county's literal full addresses. The sixth permit supplied a unit number and omitted the building. Exactly one of the 587 address points at that street contained the full unit identifier. Its point fell strictly inside the polygon with the same PIN. All 86 earlier matches still had the same unique parcel. [Private address-point lookup](../cre/ingestion/gwinnett_address_points.py)

The November 20 Site Address Point snapshot has 416,661 features in EPSG:2240. The retained file, county catalog and feature count were verified. The operator can include points marked Primary, Secondary or Tertiary. A point contributes a candidate when its address matches and its PIN agrees with the single active polygon covering its location. The lookup searches across buildings when the query supplies a unit alone, preserves complete identifiers and retains conflicting point evidence for review. It uses the expected PIN only when scoring. The county permits private internal use and prohibits redistribution or sale. [County item and terms](https://gcgis-gwinnettcountyga.hub.arcgis.com/api/v3/datasets/37205351432348f887d1bef3eb80ddcd_0)

| Reason a parcel could not be returned | Cases | Evidence |
| --- | ---: | --- |
| Incomplete suite or building evidence | 4 | The county points omit the queried suite, part of a two-part qualifier, or a letter in the unit ID. At one site the shorter numeric ID names a unit on a different parcel. |
| Missing house number | 1 | The assessor and three county points name the street but omit the permit's house number. |
| Condominium with a shared polygon | 1 | The county condo and tax tables confirm the unit PIN and the permit street. The point confirms the unit and parent PINs, with a different street suffix. The active parent polygon serves 98 units. |
| Polygon held over a shared secondary key | 1 | An exact primary point lies strictly inside the held polygon. Parcel and tax records corroborate its primary identity. Seven GIS features use its secondary key. |
| Unqualified address shared by two parcels | 1 | Fifteen building- or suite-qualified points span two parcels. Both parcels have a primary building point. The permit street gives no building qualifier. |

The last three cases have a private adjudication record with county row locators and native-coordinate containment checks. The later identity lookup incorporated the corroborated condo and held polygon. The 92-match evaluation counted parcels returned by the GIS, assessor and address-point lookup at that stage. [County condominium crosswalk](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/10) · [County parcel view](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/6) · [County tax master](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/9)

The private evidence root is `.local/gwinnett-review/`. It contains the point acquisition in `address-points/receipt.json`, the three parcel decisions in `parcel-reconciliation/adjudication.json`, and the frozen benchmark in `parcel-benchmark-2026-11-23/`. The final per-case result is `score-address-points-v2.json` (SHA-256 `64804c53cf09eadf331e6368e36517e78c0ecd13e853a50d022df7c81b9d52fc`). The independent raw-file results and replay scripts are in `address-points-independent/` alongside it.

To run this evaluation, add `--address-points` to either the private `lookup-address` command or the benchmark command below and choose a fresh output filename.

### Historical private lookup with assessor site addresses

**November 23, 2026 — 86 of 100 correct.** The pilot requires 98. On the same frozen permit addresses used for the GIS baseline, 86 returned the expected parcel as the sole candidate, and 14 returned no candidate. There were zero ambiguous results and zero wrong unique results. All 100 cases remained in the denominator. This measures private full-street lookup for one week of permitted properties. Human review of the labels remains open.

The private index contains 303,186 literal `PROPERTYSTREET` values, one for each accepted ownership-to-parcel link. The operator lookup searches that field and the original GIS address, ignores case and surrounding spaces, and counts distinct active parcels. It retains units and range text. The expected PIN is consulted only after candidate retrieval. Each match includes the address field’s source record and locator and the GIS feature that supplied the parcel PIN. [Private lookup and scoring](../cre/ingestion/gwinnett_lookup.py)

An independent read of the original workbook confirmed the literal cell value at all 303,186 indexed row positions. Replaying the index produced the same count. A separate scan of the published parcels reproduced all 100 case outcomes. The private database verifier passed its parcel, ownership, companion, site-address and access checks.

| Reason for no match | Cases |
| --- | ---: |
| Permit adds unit, range, or other text to the assessor’s base street | 6 |
| Expected active parcel has a different house number or street, or lacks the permit’s house number | 4 |
| Active parcel has no ownership row at its GIS tax PIN | 1 |
| GIS feature is held because its secondary identifier is shared with other features | 2 |
| Expected PIN is absent from the original GIS export | 1 |

Both held features have a GIS land-record number that also disagrees with the assessor row identified by their tax PIN. The subsequent address-point evaluation above records the independent parcel evidence. [County address layer](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/0)

The private case results are in `.local/gwinnett-review/parcel-benchmark-2026-11-23/score-situs-v1.json` (SHA-256 `9d56b92819ac649599cb2d36d57048a4ee97acf827a3f31fff1e795812aac931`). The scorer records the label and source digests, publication IDs, per-case outcomes and matching citations. To repeat the run from the project root, use a fresh private directory for its output.

```sh
bundle=.local/gwinnett-review/parcel-benchmark-2026-11-23
replay_dir=$(mktemp -d "$bundle/replay.XXXXXXXX")
scripts/gwinnett-internal benchmark-addresses "$bundle/frozen-labels.csv" \
  --sha256 517a51c418c02fe9e097c5dbb78a1ffbb448024033bf58b4e44adc73806bc1f3 \
  --output "$replay_dir/score.json"
```

A completed run below 98 writes the report and exits with status 1.

### Historical GIS-address baseline

**November 23, 2026 — 0 of 100 correct.** The pilot requires 98 correct matches. All 100 full street addresses returned zero candidates from the November 20 private GIS publication. A second read-only scan of all 305,161 active parcels reproduced every outcome. [Pilot release criteria](../infrastructure/PILOT.md#evidence-for-releasing-gwinnett)

Gwinnett Planning and Development printed a site address and parcel number together on each of its 137 permits for November 9–13. The report contained 134 distinct parcel numbers. Before scoring, the evaluator kept the first permit per parcel and selected 100 using a fixed SHA-256 ordering. Each query retained the street and any unit as printed, with the city recorded separately. A second Codex agent independently transcribed the report and checked all 100 selected cases against the rendered pages while blinded to match results. Both transcriptions agreed on every label. Human review of this benchmark sample is still outstanding. The sample covers full-address lookup for parcels with permit activity that week. Point lookup and countywide accuracy remain unmeasured. [County permit report](https://www.gwinnettcounty.com/documents/d/gwinnett-county/gwinnett-county-building-permits-issued-11-9-11-13)

The scorer applied the repository benchmark’s trimmed, case-insensitive exact address comparison to current, active Gwinnett geometries in private run `5332efd6-1c38-4e94-b18d-ef721696393b`. A correct result required exactly one candidate with the permit’s normalized GIS PIN. The expected PIN was used only after candidate retrieval. [Benchmark scoring rule](../cre/ingestion/__main__.py)

Looking up the expected PINs after scoring identified the address coverage issue.

| Status of the expected parcel | Cases |
| --- | ---: |
| Present with only the house number printed on the permit | 93 |
| Present with a different stored address value | 3 |
| Present with an empty address | 1 |
| Absent from the active publication | 3 |

Across the entire publication, 296,088 parcel addresses contained only digits and 9,066 were blank. None contained an internal space after trimming. The original GIS export contained 99 of the 100 expected PINs. For 94 of those 99, its address field held only the permit’s house number.

The private evidence directory is `.local/gwinnett-review/parcel-benchmark-2026-11-23/`. It contains the source PDF, `freeze-manifest.json`, the frozen labels with permit and page references, the blinded check in `second-review/verification.json`, the archived GIS-only scorer, and its original per-case result in `score.json` (SHA-256 `7d875823ed6eb1926818a3bc6b17dc4920b807404b7610b279823c17d52a67d6`). For a historical replay, copy the archived `score.py` to a new owner-only directory under `.local/gwinnett-review/` first. It writes `score.json` beside its script.
