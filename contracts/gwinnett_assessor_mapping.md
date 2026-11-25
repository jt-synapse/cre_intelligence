# Gwinnett assessor ownership workbook, October 2026 release

The county offers a quarterly ZIP for download. This review covers one copy retrieved November 22, 2026 in Georgia (November 23 UTC). The archive is 239,605,057 bytes. Its SHA-256 is `e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca`. The five ZIP entries carry October 5, 2026 file timestamps. October 5 is a package date. The county download page provides no quarter-end ownership certification or exact effective date for every parcel. [County download page](https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database) · [Original ZIP](https://www.gwinnettcounty.com/content/departments/its/gis-maps/tax_assessor_property_ownership_data.zip)

## Archive inventory

All five workbooks are under `tax_assessor_property_ownership_data/` and use `Sheet1`. The archive contains these files and its enclosing directory entry. No license or readme accompanies them. The row counts in this table exclude the header and derive from the declared worksheet dimensions. A full scan counted 315,343 ownership data rows.

| Workbook | Rows | Columns | SHA-256 of original XLSX bytes |
| --- | ---: | ---: | --- |
| `2026 Property Ownership.xlsx` | 315,343 | 42 | `feb978febd1fcd55a6edd1b3476d2e161d384a98886a02e81a91694ec2c52cfa` |
| `CamaFull_Improv.xlsx` | 308,830 | 82 | `1546c4bf2ace94b41397f649c8a926f0d01b676489d5b4ea7f6f9f61ced38a6c` |
| `CamaFull_Land.xlsx` | 323,701 | 107 | `de90c3ee941146aca6bf374e2d8859ae7ce822a1e13af74e02b21fba72fbb262` |
| `Property Class Code List 2026.xlsx` | 284 | 6 | `ec55fbf351b6d47b8ae7d60c29a33c2945f8046814573c2685aabae72839a8a0` |
| `TAX DIGEST OWNERSHIP LAYOUT.xlsx` | 42 | 5 | `96d7c718f713c8ce5778fcc98e224ff08f79f79aa2a275d84ec7a69feb890d19` |

Mapping version `2` reads only `2026 Property Ownership.xlsx` from the complete ZIP. The other four files have distinct layouts and are declared companion files. The parser checks the complete member inventory before yielding rows and checks all 42 ownership headers. Citations identify the original workbook, sheet, one-based Excel row and source field. The county layout lists `CHAR` or `VARCHAR` storage types. The counts below use the actual Excel cell types. [Reviewed manifest](gwinnett_assessor.json)

## Ownership field mapping

| County field | Operator mapping | Nonblank Excel values | Interpretation |
| --- | --- | ---: | --- |
| `PIN` | `pin` | 315,343 text | County assessor identifier. Match to GIS `TAXPIN` as source text. |
| `LRSNum` | `source_lrsn` | 315,343 integer | Corroboration when present in GIS. A disagreement requires review. |
| `OWNERNAME1` | `owner` | 315,343 text | Assessor-listed ownership line 1. Keep the record tied to its parcel and observation. |
| `OWNERNAME2` | `owner_line_2` | 108,670 text | Preserve the second source line as recorded. Its contents alone do not establish a separate person, entity or ownership share. |
| `OWNERADDRESS1` | `mailing_street` | 315,339 text, 4 numeric | Source mailing address line. |
| `OWNERCITY` | `mailing_city` | 315,338 text, 2 numeric | Source mailing city. |
| `OWNERSTATE` | `mailing_state` | 315,255 text | Source mailing state. |
| `OWNERZIP` | `mailing_zip` | 310,391 text, 4,869 numeric | Preserve text and numeric values as recorded. Of the numeric cells, 2 have three stored digits and 19 have four. |
| `TOTVAL1` | `source_total_value` | 314,999 numeric | County label “Total Value.” |
| `TAXTOT1` | `source_tax_total` | 314,999 numeric | County label “Tax Total.” |

All four mailing components are populated on 315,255 rows. Every second ownership line accompanies a first line. The `PROPERTY*` fields describe the property location. They are distinct from the `OWNER*` mailing components.

The private address index projects the literal `PROPERTYSTREET` cell from an accepted ownership workbook row onto its linked parcel. A citation identifies the retained workbook, sheet, Excel row and field. The projection can be rebuilt from the retained release with `scripts/gwinnett-internal index-situs`. [Private lookup instructions](README.md#import-the-gwinnett-snapshots-privately)

The county GIS field dictionary labels the two totals. On all 314,999 rows with values, `TOTVAL1` equals `LANDVAL1 + DWLGVAL1 + OTHVAL1`, and `TAXTOT1` equals `TAXLAND1 + TAXDWLG1 + TAXOTH1`. On the 314,423 rows with positive `TOTVAL1`, `TAXTOT1` is within one stored unit of 40% of that amount. These checks support preserving both literal fields. Mapping a canonical assessed value, tax liability or valuation basis requires a definition specific to this release. [County GIS field dictionary](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Parcel/MapServer/6)

The layout has no `tax_year` column. The Excel date field `ASSMNT1D` contains January 1, 2026 on 314,977 rows, January 1 of an earlier year on 22 rows and no value on 344 rows. The oldest recorded year is 2004. A uniform per-row tax year cannot be derived from the filename.

## Full GIS crosswalk

The comparison scanned all 309,555 features in the November 20, 2026 Gwinnett GIS export and every ownership row. The GIS file SHA-256 is `7bc547068cfaea1d884f9819bc304dabb79872f9d5c254185753561d5b4222e0`. Each workbook `PIN` and `LRSNum` is populated and unique. Normalizing PINs by trimming, uppercasing and removing whitespace and hyphens also yields 315,343 distinct values. [County Land Parcels catalog](https://gcgis-gwinnettcountyga.hub.arcgis.com/datasets/340cdb68491e49bea5236cecdf66f658_0)

| GIS comparison | Matching GIS features | Distinct ownership rows reached |
| --- | ---: | ---: |
| GIS `PIN` to assessor `PIN` after normalization | 0 | 0 |
| GIS `TAXPIN` to assessor `PIN`, exact source text | 304,549 | 304,520 |
| GIS `LRSN` to assessor `LRSNum`, integer equality | 278,084 | 277,680 |
| Both `TAXPIN` and `LRSN` agree on the same assessor row | 277,700 | 277,674 |

Use `TAXPIN` as the join and `LRSN` for corroboration. Normalizing `TAXPIN` produced the same matches as exact source text. On 384 GIS features the two keys independently identify different ownership rows. Another 26,465 GIS features match by `TAXPIN` only. An `LRSN` fallback adds zero features. Across the GIS input, 26 normalized `TAXPIN` values occur on multiple features and 160 non-null `LRSN` values occur on multiple features. Record ambiguities and disagreements for review. These raw join counts precede geometry validation and parcel publication, and they measure key coverage only.

## Companion worksheet index

Run `scripts/gwinnett-internal index-companions` after the ownership baseline has been published. The command indexes the four companion worksheets from the same retained ZIP. It verifies the archive digest, private source policy and release-specific row counts. An identical rerun checks the existing index.

| Companion worksheet | Indexed source rows | Linked ownership source rows, counting each companion line |
| --- | ---: | ---: |
| CAMA improvements | 308,830 | 305,803 |
| CAMA land | 323,701 | 315,343 |
| Property class code list | 284 | — |
| Tax digest ownership layout | 42 | — |

A CAMA line links when its literal `PIN` and integer `LRSNum` agree with a unique row of the ownership workbook. Both CAMA files also carry a trailing `LRSN` that agrees with `LRSNum` on every line. Across the two sheets, 11,385 lines retain their original worksheet positions with an empty ownership link. A link identifies a row in the assessor release, including ownership rows held from GIS publication.

The private `staging.gwinnett_companion_workbook` table records the parent assessor run, original XLSX member path and SHA-256, sheet name and headers in Excel column order. The `staging.gwinnett_companion_row` table records the workbook ID and one-based Excel row. The header position gives the source column. Use these positions to retrieve CAMA field values from their original cells in the retained workbooks. Rows from the two small reference dictionaries also retain their ordered source values in `reference_cells`. These source indexes create no building, sale, land-use or title claims.

## Scope of use

The download page instructs users to save a copy of the quarterly data. The private operator evaluation treats temporary retention and structured inspection as uses implied by that instruction. The manual acquisition decision covers the dedicated private working copy and its private derivatives while needed for this evaluation. Automation, shared display, customer export and commercial redistribution remain unapproved. Recheck the county terms before acquiring another release. [County distribution terms and instructions](https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database)
