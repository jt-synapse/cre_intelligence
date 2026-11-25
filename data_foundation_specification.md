# **CRE Intelligence Platform — Data Foundation Specification**

Engineering specification · DF-001 · Version 1.0 · November 22, 2026

**Scope:** Canonical relational schema, data source provisioning, source normalization, identity resolution, historical records, evidence provenance, and ingestion validation.

**Implementation target:** PostgreSQL + PostGIS, Python + FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, and S3-compatible object storage.

This specification establishes the data foundation for the broader CRE operations platform. It deliberately excludes frontend development, LLM agent execution, contact outreach, and full financial underwriting.

## **1. Foundation decisions**

The system must distinguish five fundamental concepts:

- **Parcel:** A legally or administratively identified unit of land within a jurisdiction.
- **Property:** A real-world commercial asset, potentially comprising multiple parcels and buildings.
- **Party:** An individual or organization involved in ownership, management, leasing, financing, or business operations.
- **Claim:** An assertion about a property or party, supported by evidence and potentially disputed.
- **Operational record:** A customer-owned portfolio, opportunity, task, research finding, or document associated with those entities.

These concepts must remain separate. Combining them into a single `properties` table would create significant problems with ownership history, corporate relationships, multiple parcels, and future development.

### **Architectural decisions**

| ID      | Decision                                                             | Rationale                                                       |
| ------- | -------------------------------------------------------------------- | --------------------------------------------------------------- |
| ADR-001 | Use PostgreSQL + PostGIS as the system of record                     | Supports structured, spatial, temporal and relationship queries |
| ADR-002 | Use internal UUIDs for all primary keys                              | Avoids dependence on unstable vendor identifiers                |
| ADR-003 | Separate parcels from properties                                     | Supports multi-parcel assets, subdivisions, and assemblages     |
| ADR-004 | Represent individuals and organizations through a common party model | Supports corporate ownership networks and contact relationships |
| ADR-005 | Store immutable source versions and separately versioned claims      | Enables reproducibility, corrections and audits                 |
| ADR-006 | Preserve competing assertions                                        | Prevents silent loss of contradictory evidence                  |
| ADR-007 | Separate shared/reference data from tenant-owned operational data    | Supports multiple CRE organizations securely                    |
| ADR-008 | Treat LLM enrichment as proposed evidence, not authoritative data    | Prevents generated conclusions from silently becoming facts     |
| ADR-009 | Implement source-specific licensing and retention policies           | Prevents inappropriate use or redistribution of external data   |

## **2. Verified Georgia data availability**

Research confirms that Gwinnett County offers a workable initial data environment.

**Parcel geometry and identifiers**

Gwinnett exposes an ArcGIS parcel FeatureServer with polygon geometry, `PIN`, `TAXPIN`, `LRSN`, `ADDRESS`, deeded acreage, and calculated acreage fields. Its documented output formats include GeoJSON, with a 2,000-record maximum per query response. The published source coordinate system is Georgia State Plane West, EPSG:2240.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://services3.arcgis.com\&sz=32)

services3.arcgis.com



[Inspect the actual parcel feature layer](https://services3.arcgis.com/RfpmnkSAQleRbndX/ArcGIS/rest/services/Property_and_Tax/FeatureServer/0?utm_source=chatgpt.com)

**Ownership and tax assessments**

Gwinnett also publishes a downloadable ZIP containing XLSX files with parcel ownership and value information. The county states that this ownership database is updated quarterly. The initial pipeline should treat it as a separate source from the polygon feature layer.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.gwinnettcounty.com\&sz=32)

Gwinnett



[Gwinnett ownership dataset](https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database?utm_source=chatgpt.com)

**Recorded deeds and instruments**

GSCCCA provides statewide real estate indexes, deed references, liens and instrument images, subject to its access model. Some search capabilities require paid access. No unrestricted automated ingestion or commercial reuse right has been established.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://search.gsccca.org\&sz=32)

GSCCCA+1



[Georgia Real Estate Index](https://search.gsccca.org/RealEstate/?utm_source=chatgpt.com)

**Business registrations**

Georgia's Secretary of State supports searching by business name, control number, registered agent name and officer name. Critically, Georgia LLC filings generally do not disclose LLC officers or beneficial owners, and the registry does not supply business telephone numbers. This will shape the ownership investigation model.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://sos.ga.gov\&sz=32)

Georgia Secretary of State+1



[Georgia business entity search](https://ecorp.sos.ga.gov/businesssearch?utm_source=chatgpt.com)

**Provisioning decision:** Start with the verified Gwinnett parcel layer and quarterly ownership export. Treat GSCCCA and Secretary of State research as human-assisted or otherwise explicitly authorized data acquisition until automation rights are confirmed.

The first production-quality workflow will therefore be **parcel geometry → ownership enrichment → source-backed canonical property record**, with corporate and deed records added as controlled investigations.

## **3. Canonical relational data model**

I recommend dividing the database into five PostgreSQL schemas:

| Schema       | Responsibility                                                       |
| ------------ | -------------------------------------------------------------------- |
| `core`       | Canonical properties, parcels, buildings, parties and ownership      |
| `provenance` | Source catalogs, ingestion runs, raw records and source versions     |
| `evidence`   | Assertions, supporting records, conflicts and verification decisions |
| `operations` | Tenant-owned portfolios, opportunities, contacts and tasks           |
| `staging`    | Temporary normalized records awaiting validation and publication     |

The first three are required for the data foundation milestone. `operations` is defined now but implemented with the subsequent operations milestone. Staging data is disposable; canonical and historical evidence data is not.

### **3.1 Core table contracts**

| Table                     | Critical fields                                                      | Required constraints                            |
| ------------------------- | -------------------------------------------------------------------- | ----------------------------------------------- |
| `jurisdiction`            | `id`, `county_fips`, `state_code`, `name`                            | Unique county FIPS                              |
| `address`                 | `id`, address components, location, geocode quality                  | Preserve original and normalized values         |
| `parcel`                  | `id`, `jurisdiction_id`, `primary_pin`, `parcel_state`, `retired_at` | Unique current PIN within jurisdiction          |
| `parcel_identifier`       | `parcel_id`, `source_id`, `identifier_type`, `identifier_value`      | Preserve source aliases and old IDs             |
| `parcel_geometry_version` | `parcel_id`, polygon, observation period, source record              | Valid PostGIS geometry; one current version     |
| `property`                | `id`, `name`, `asset_class`, `property_status`                       | No assumed one-to-one parcel relationship       |
| `property_parcel`         | `property_id`, `parcel_id`, validity interval, role                  | Foreign keys and temporal integrity             |
| `building`                | `id`, `property_id`, gross area, year built                          | Nullable unverified attributes                  |
| `party`                   | `id`, `party_type`, canonical name                                   | Person or organization                          |
| `entity_registration`     | `party_id`, jurisdiction, registry ID, status                        | Unique registry identifier within jurisdiction  |
| `party_relationship`      | Source party, target party, relationship type, dates                 | No implied ownership from shared attributes     |
| `ownership_record`        | Property/parcel, owner party, effective interval, source             | Evidence reference required for verified status |

I would use controlled vocabularies for fields such as asset class, relationship type and ownership record state, rather than letting arbitrary LLM-generated strings enter the database.

Asset classes should include at least `office`, `industrial`, `retail`, `multifamily`, `hospitality`, `land`, `mixed_use`, `special_purpose` and `unknown`. Classifications should support finer subtypes later.

### **3.2 Key relationship rules**

\#chatgpt-mermaid-\_r_1na\_{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;fill:rgb(191, 189, 182);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_1na\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_1na\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_1na\_ .error-icon{fill:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_1na\_ .error-text{fill:rgb(191, 189, 182);stroke:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1na\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_1na\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_1na\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_1na\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_1na\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_1na\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_1na\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1na\_ .marker.cross{stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1na\_ svg{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;}#chatgpt-mermaid-\_r_1na\_ p{margin:0;}#chatgpt-mermaid-\_r_1na\_ .entityBox{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_1na\_ .relationshipLabelBox{fill:rgba(191, 189, 182, 0.03);opacity:0.7;background-color:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_1na\_ .relationshipLabelBox rect{opacity:0.5;}#chatgpt-mermaid-\_r_1na\_ .labelBkg{background-color:rgba(191, 189, 182, 0.5);}#chatgpt-mermaid-\_r_1na\_ .edgeLabel{background-color:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_1na\_ .edgeLabel .label rect{fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_1na\_ .edgeLabel .label text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1na\_ .edgeLabel .label{fill:rgb(108, 163, 252);font-size:14px;}#chatgpt-mermaid-\_r_1na\_ .label{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1na\_ .edge-pattern-dashed{stroke-dasharray:8,8;}#chatgpt-mermaid-\_r_1na\_ .node rect,#chatgpt-mermaid-\_r_1na\_ .node circle,#chatgpt-mermaid-\_r_1na\_ .node ellipse,#chatgpt-mermaid-\_r_1na\_ .node polygon{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_1na\_ .relationshipLine{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;fill:none;}#chatgpt-mermaid-\_r_1na\_ .marker{fill:none!important;stroke:rgba(191, 189, 182, 0.498)!important;stroke-width:1;}#chatgpt-mermaid-\_r_1na\_ [data-look=neo].labelBkg{background-color:rgba(191, 189, 182, 0.5);}#chatgpt-mermaid-\_r_1na\_ .node .neo-node{stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_1na\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_1na\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node .neo-line path{stroke:rgb(108, 163, 252);filter:none;}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_1na\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_1na\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1na\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_1na\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1na\_ :root{--mermaid-font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;}JURISDICTIONPARCELPARCEL_IDENTIFIERPARCEL_GEOMETRY_VERSIONPROPERTYPROPERTY_PARCELBUILDINGPARTYENTITY_REGISTRATIONPARTY_RELATIONSHIPOWNERSHIP_RECORDINGESTION_RUNSOURCE_RECORDCLAIM_SUPPORTEVIDENCE_CLAIMcontainsidentified_byversioned_ascomprisesincluded_incontainsregistered_asparticipates_inrecorded_interestnamed_partycapturesprovidessupported_by

A particularly important relationship is `property_parcel`. It allows multiple parcels to form one investable property without forcing the legal parcels to become a single geographic object.

### **3.3 Migration-ready foundational SQL**

The following establishes the principal physical tables for parcel and source ingestion. It is intended as the first Alembic migration baseline, with additional evidence, corporate and operations tables introduced in subsequent migrations.

```

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS provenance;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS operations;
CREATE SCHEMA IF NOT EXISTS staging;

-- Sources are governed separately from their datasets.
CREATE TABLE provenance.source_system (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    publisher TEXT,
    homepage_url TEXT,
    access_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (access_status IN (
            'pending_review', 'approved',
            'restricted', 'disabled'
        )),
    license_reference TEXT,
    attribution TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE provenance.source_dataset (
    id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL
        REFERENCES provenance.source_system(id),
    jurisdiction_fips CHAR(5),
    resource_url TEXT,
    source_format TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    refresh_policy TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE provenance.ingestion_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id TEXT NOT NULL
        REFERENCES provenance.source_dataset(id),
    input_fingerprint CHAR(64) NOT NULL,
    mapping_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'acquiring', 'staging',
            'validating', 'ready_to_publish',
            'published', 'failed', 'quarantined'
        )),
    records_read INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (dataset_id, input_fingerprint, mapping_version)
);

-- Immutable source snapshots. Never overwrite raw payloads.
CREATE TABLE provenance.source_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL
        REFERENCES provenance.ingestion_run(id),
    external_record_id TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    raw_object_uri TEXT NOT NULL,
    source_modified_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, external_record_id)
);

CREATE TABLE core.jurisdiction (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    county_fips CHAR(5) NOT NULL UNIQUE,
    state_code CHAR(2) NOT NULL,
    county_name TEXT NOT NULL
);

CREATE TABLE core.parcel (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jurisdiction_id UUID NOT NULL
        REFERENCES core.jurisdiction(id),
    primary_pin TEXT,
    normalized_pin TEXT,
    parcel_state TEXT NOT NULL DEFAULT 'active'
        CHECK (parcel_state IN (
            'active', 'retired', 'pending_review'
        )),
    retired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_parcel_current_pin
ON core.parcel (jurisdiction_id, normalized_pin)
WHERE retired_at IS NULL AND normalized_pin IS NOT NULL;

CREATE TABLE core.parcel_identifier (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES core.parcel(id),
    source_system_id TEXT NOT NULL
        REFERENCES provenance.source_system(id),
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT true,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ
);

CREATE INDEX ix_parcel_identifier_lookup
ON core.parcel_identifier (
    source_system_id, identifier_type, identifier_value
);

CREATE TABLE core.parcel_geometry_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES core.parcel(id),
    source_record_id UUID NOT NULL
        REFERENCES provenance.source_record(id),
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL,
    calculated_acres NUMERIC(16,6),
    is_current BOOLEAN NOT NULL DEFAULT false,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_from DATE,
    effective_to DATE,
    CHECK (ST_IsValid(geom)),
    CHECK (
        effective_to IS NULL OR effective_from IS NULL
        OR effective_to >= effective_from
    )
);

CREATE UNIQUE INDEX ux_current_parcel_geometry
ON core.parcel_geometry_version(parcel_id)
WHERE is_current = true;

CREATE INDEX ix_parcel_geometry_spatial
ON core.parcel_geometry_version USING GIST(geom);

CREATE TABLE core.property (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    asset_class TEXT NOT NULL DEFAULT 'unknown',
    property_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.property_parcel (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES core.property(id),
    parcel_id UUID NOT NULL REFERENCES core.parcel(id),
    relationship_type TEXT NOT NULL DEFAULT 'component',
    valid_from DATE,
    valid_to DATE,
    CHECK (
        valid_to IS NULL OR valid_from IS NULL
        OR valid_to >= valid_from
    )
);

```

The indexes are intentionally selective. Additional indexes should be added using measured query plans, rather than indexing every field in anticipation of future workloads.

A few details need to be enforced in the application or subsequent migrations:

- The source snapshot must be persisted before its `source_record` metadata is committed.
- The current geometry pointer must be updated transactionally. A prior version should be demoted when a new current version is published.
- The parcel identifier table must preserve the original identifier string, including leading zeros and punctuation.
- Historical parcel identifiers must not be globally treated as permanently unique. An assessor may renumber, split, merge or reuse identifiers.
- Property-to-parcel associations need duplicate suppression and interval-overlap validation.
- Publishing a canonical change and recording its provenance must happen in the same database transaction.

### **3.4 Corporate identity and ownership contracts**

The LLC investigation needs flexible but rigorously typed identity records.

```

CREATE TABLE core.party (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_type TEXT NOT NULL
        CHECK (party_type IN ('person', 'organization')),
    display_name TEXT NOT NULL,
    normalized_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.entity_registration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_id UUID NOT NULL REFERENCES core.party(id),
    jurisdiction_code TEXT NOT NULL,
    registration_number TEXT NOT NULL,
    legal_name TEXT NOT NULL,
    entity_type TEXT,
    registration_status TEXT,
    source_record_id UUID
        REFERENCES provenance.source_record(id),
    UNIQUE (jurisdiction_code, registration_number)
);

CREATE TABLE core.party_relationship (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_party_id UUID NOT NULL REFERENCES core.party(id),
    object_party_id UUID NOT NULL REFERENCES core.party(id),
    relationship_type TEXT NOT NULL,
    verification_state TEXT NOT NULL DEFAULT 'candidate',
    valid_from DATE,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (subject_party_id <> object_party_id)
);

CREATE INDEX ix_relationship_subject
ON core.party_relationship(subject_party_id);

CREATE INDEX ix_relationship_object
ON core.party_relationship(object_party_id);

CREATE TABLE core.ownership_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID REFERENCES core.parcel(id),
    property_id UUID REFERENCES core.property(id),
    owner_party_id UUID NOT NULL REFERENCES core.party(id),
    ownership_kind TEXT NOT NULL DEFAULT 'recorded_title',
    valid_from DATE,
    valid_to DATE,
    verification_state TEXT NOT NULL DEFAULT 'candidate',
    source_record_id UUID NOT NULL
        REFERENCES provenance.source_record(id),
    CHECK (num_nonnulls(parcel_id, property_id) = 1),
    CHECK (
        valid_to IS NULL OR valid_from IS NULL
        OR valid_to >= valid_from
    )
);

```

These tables store proposed and verified relationships, but **they do not authorize promotion to verified status on their own**. The evidence service must require adequate supporting records before changing verification state.

The initial relationship vocabulary should include `registered_agent_for`, `disclosed_manager_of`, `officer_of`, `documented_member_of`, `asset_manager_for`, `property_manager_for`, `business_contact_for`, and `potential_affiliate_of`. Potential affiliation must remain distinguishable from confirmed control.

### **3.5 Evidence and claim architecture**

An evidence claim is different from a raw source record.

A raw assessor record might contain the text `OWNER1 = PEACHTREE HOLDINGS LLC`. The corresponding claim is that *a particular assessor snapshot names that entity as owner of a particular parcel*. That does not, by itself, prove current title, ownership percentages, or the entity's beneficial owner.

The claim schema should contain:

| Field                         | Type                 | Purpose                                                              |
| ----------------------------- | -------------------- | -------------------------------------------------------------------- |
| `id`                          | UUID                 | Unique claim                                                         |
| `subject_type` / `subject_id` | Enum + UUID          | Entity the claim concerns                                            |
| `predicate`                   | Text/controlled code | Nature of assertion                                                  |
| `value`                       | JSONB                | Structured claim value                                               |
| `valid_from`, `valid_to`      | Date                 | Period asserted to apply                                             |
| `observed_at`                 | Timestamp            | When the information was observed                                    |
| `verification_state`          | Enum                 | Candidate, verified, conflicted, stale, etc.                         |
| `reviewed_by`, `reviewed_at`  | Nullable             | Human review provenance                                              |
| `supersedes_claim_id`         | Nullable UUID        | Historical correction relationship                                   |
| `extraction_method`           | Enum                 | Direct mapping, deterministic extraction, AI extraction, human entry |

A separate `claim_support` table joins claims to one or more `source_record` entries, with a document page, excerpt locator or structured field path.

Use an append-only `claim_review_event` table to preserve every promotion, rejection, correction and conflict decision.

The principal rule is:

**A source record supports a claim; a claim does not become a fact merely because an LLM extracted it.**

This model also allows a property report to display both the canonical selected value and the competing evidence behind it.

## **4. Source provisioning contracts**

Each data source requires a machine-readable contract defining where data originates, how it is acquired, how it is transformed, what qualifies as a valid record, and whether its use is authorized.

### **4.1 Gwinnett parcel geometry manifest**

This manifest uses verified metadata from the county's actual ArcGIS layer. Automated acquisition remains conditional on a source-access and usage-rights review.

```

manifest_version: "1.0"

source:
  id: gwinnett_gis
  publisher: Gwinnett County, Georgia
  type: government_gis
  access_status: pending_review

dataset:
  id: ga_gwinnett_parcels
  category: parcel_geometry
  county_fips: "13135"
  mapping_version: "1.0.0"

resource:
  type: arcgis_feature_layer
  url: >-
    https://services3.arcgis.com/RfpmnkSAQleRbndX/ArcGIS/rest/services/Property_and_Tax/FeatureServer/0
  layer_id: 0
  geometry_type: polygon
  native_srid: 2240
  supported_output: geojson
  max_records_per_request: 2000

acquisition:
  mode: manual_export_until_approved
  planned_mode: paginated_query
  planned_page_size: 1000
  planned_order_by: OBJECTID
  refresh: on_demand_initially
  retry_policy: exponential_backoff

identity:
  primary_field: PIN
  alternate_fields:
    - TAXPIN
    - LRSN
  namespace: "ga:13135:parcel"

mapping:
  PIN: parcel.primary_pin
  TAXPIN: parcel_identifier.tax_pin
  LRSN: parcel_identifier.lrsn
  ADDRESS: address.raw_address
  DEEDEDACREAGE: observation.deeded_acres
  CALCULATEDACREAGE: observation.gis_acres
  geometry: parcel_geometry_version.geom

transform:
  preserve_original_identifiers: true
  normalize_pin: county_specific_v1
  target_srid: 4326
  polygon_to_multipolygon: true
  preserve_raw_geometry: true

validation:
  require_primary_identifier: true
  require_valid_geometry: true
  require_supported_srid: true
  quarantine_on_identity_collision: true
  prohibit_silent_geometry_repair: true

publication:
  require_completed_validation: true
  retain_previous_versions: true
  store_source_record_reference: true

governance:
  commercial_use: pending_review
  automated_access: pending_review
  redistribution: pending_review
  retention_policy: pending_review

```

The source metadata establishes the `PIN`, `TAXPIN`, `LRSN` and acreage fields as real fields on the parcel layer. We should inspect pagination behavior during a small approved test before treating full county extraction as operationally supported.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://services3.arcgis.com\&sz=32)

services3.arcgis.com



A separate Gwinnett map service also exposes `OWNER1`, `OWNER2`, mailing address, zoning, assessed-value-related fields, and deed-reference fields. This makes it a useful candidate for ownership enrichment, but its values require mapping and reconciliation before they can be promoted to canonical facts.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://gis3.gwinnettcounty.com\&sz=32)

gis3.gwinnettcounty.com



### **4.2 Gwinnett ownership data manifest**

The assessor's ownership export needs a different contract because it is a ZIP/XLSX distribution rather than a parcel geometry layer.

```

manifest_version: "1.0"

source:
  id: gwinnett_assessor
  publisher: Gwinnett County
  access_status: pending_review

dataset:
  id: ga_gwinnett_ownership
  category: assessor_ownership
  county_fips: "13135"
  mapping_version: "0.1.0"

resource:
  type: zip_xlsx
  distribution_page: >-
    https://www.gwinnettcounty.com/government/departments/county-administrator/assessor/property-ownership-database
  published_refresh: quarterly
  sheet_names: pending_inspection

acquisition:
  mode: manual_import_initially
  accepted_extensions:
    - .zip
    - .xlsx
  preserve_original: true

identity:
  parcel_join_field: pending_inspection
  parcel_join_namespace: "ga:13135:parcel"

mapping:
  owner_name: pending_inspection
  mailing_address: pending_inspection
  assessed_value: pending_inspection
  tax_year: pending_inspection

validation:
  reject_missing_source_identity: true
  quarantine_ambiguous_parcel_matches: true
  preserve_original_owner_text: true
  flag_conflicting_owner_names: true
  forbid_inferred_beneficial_ownership: true

publication:
  canonical_owner_kind: assessor_listed_owner
  verification_required: true

governance:
  license_status: pending_review
  external_redistribution: pending_review

```

The `pending_inspection` entries are intentional. They must be replaced with the actual workbook sheet names and column headers after examining a current distribution. The source page confirms the distribution and quarterly cadence, not every spreadsheet field or workbook structure.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.gwinnettcounty.com\&sz=32)

Gwinnett



### **4.3 Future source adapters**

Define their interfaces now but defer implementation until M0 or M2 requires them.

| Connector           | Initial execution                       | Canonical output                                               |
| ------------------- | --------------------------------------- | -------------------------------------------------------------- |
| GSCCCA deed records | Authorized manual document/index import | Deed instrument, grantor, grantee, dates, recorded references  |
| Georgia SOS         | Authorized manual registry lookup       | Entity registration, registered agent, disclosed relationships |
| Census Geocoder     | API-backed server-side enrichment       | Address candidates, coordinates, match quality                 |
| FEMA flood layers   | Geospatial import                       | Hazard-layer geometry and overlay observations                 |
| Regrid or LightBox  | Optional licensed integration           | Standardized parcel and property attributes                    |
| Customer uploads    | User-submitted CSV, XLSX, PDF           | Tenant-scoped documents, financial observations and contacts   |

The Census Geocoder supports individual and batch requests, with a documented maximum of 10,000 records per batch input. Its returned coordinates are geocoding estimates, not substitutes for authoritative parcel polygons.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://geocoding.geo.census.gov\&sz=32)

geocoding.geo.census.gov



## **5. Data ingestion lifecycle**

Every source should follow the same controlled lifecycle, while allowing format-specific adapters.

\#chatgpt-mermaid-\_r_1ok\_{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;fill:rgb(191, 189, 182);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_1ok\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_1ok\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_1ok\_ .error-icon{fill:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_1ok\_ .error-text{fill:rgb(191, 189, 182);stroke:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_1ok\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_1ok\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_1ok\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_1ok\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_1ok\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1ok\_ .marker.cross{stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1ok\_ svg{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;}#chatgpt-mermaid-\_r_1ok\_ p{margin:0;}#chatgpt-mermaid-\_r_1ok\_ .label{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .cluster-label text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .cluster-label span{color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_1ok\_ .label text,#chatgpt-mermaid-\_r_1ok\_ span{fill:rgb(191, 189, 182);color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .node rect,#chatgpt-mermaid-\_r_1ok\_ .node circle,#chatgpt-mermaid-\_r_1ok\_ .node ellipse,#chatgpt-mermaid-\_r_1ok\_ .node polygon,#chatgpt-mermaid-\_r_1ok\_ .node path{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .rough-node .label text,#chatgpt-mermaid-\_r_1ok\_ .node .label text,#chatgpt-mermaid-\_r_1ok\_ .image-shape .label,#chatgpt-mermaid-\_r_1ok\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_1ok\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .rough-node .label,#chatgpt-mermaid-\_r_1ok\_ .node .label,#chatgpt-mermaid-\_r_1ok\_ .image-shape .label,#chatgpt-mermaid-\_r_1ok\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_1ok\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_1ok\_ .root .anchor path{fill:rgba(191, 189, 182, 0.498)!important;stroke-width:0;stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1ok\_ .arrowheadPath{fill:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1ok\_ .edgePath .path{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .flowchart-link{stroke:rgba(191, 189, 182, 0.498);fill:none;}#chatgpt-mermaid-\_r_1ok\_ .edgeLabel{background-color:rgb(16, 20, 28);text-align:center;}#chatgpt-mermaid-\_r_1ok\_ .edgeLabel p{background-color:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_1ok\_ .edgeLabel rect{opacity:0.5;background-color:rgb(16, 20, 28);fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_1ok\_ .labelBkg{background-color:rgba(16, 20, 28, 0.5);}#chatgpt-mermaid-\_r_1ok\_ .cluster rect{fill:rgba(191, 189, 182, 0.03);stroke:rgba(191, 189, 182, 0.082);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .cluster text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ .cluster span{color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:12px;background:rgba(191, 189, 182, 0.03);border:1px solid rgba(191, 189, 182, 0.082);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_1ok\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_1ok\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_1ok\_ .icon-shape,#chatgpt-mermaid-\_r_1ok\_ .image-shape{background-color:rgb(16, 20, 28);text-align:center;}#chatgpt-mermaid-\_r_1ok\_ .icon-shape p,#chatgpt-mermaid-\_r_1ok\_ .image-shape p{background-color:rgb(16, 20, 28);padding:2px;}#chatgpt-mermaid-\_r_1ok\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_1ok\_ .image-shape .label rect{opacity:0.5;background-color:rgb(16, 20, 28);fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_1ok\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_1ok\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_1ok\_ .node .neo-node{stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_1ok\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_1ok\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node .neo-line path{stroke:rgb(108, 163, 252);filter:none;}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_1ok\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_1ok\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1ok\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_1ok\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_1ok\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(99, 241, 237);}#chatgpt-mermaid-\_r_1ok\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(99, 241, 237);}#chatgpt-mermaid-\_r_1ok\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_1ok\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_1ok\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(16, 20, 28);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .node rect,#chatgpt-mermaid-\_r_1ok\_ .node circle,#chatgpt-mermaid-\_r_1ok\_ .node ellipse,#chatgpt-mermaid-\_r_1ok\_ .node polygon,#chatgpt-mermaid-\_r_1ok\_ .node path{fill:rgb(0, 58, 56);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_1ok\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_1ok\_ .mermaid-decision .label-container{fill:rgb(16, 20, 28);stroke:rgb(108, 163, 252);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_1ok\_ .edgePaths .flowchart-link{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_1ok\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_1ok\_ :root{--mermaid-font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;}Register SourceAccess Approved?Manual Review / BlockAcquisitionAcquire Source SnapshotChecksum and Archive RawDataParse into StagingValidate Schema andGeometryQuality Gate Passed?Quarantine and ReviewResolve Canonical IdentitiesConflicting Match?Create Resolution TaskConstruct Source-BackedClaimsTransactional PublicationRun Reconciliation ChecksPublish Dataset VersionNoYesNoYesYesNo

### **Step 1 — Register and authorize the source**

**Concept:** Data governance precedes acquisition.

Before ingestion, record the publishing organization, data format, access method, permitted uses, retention requirements, attribution obligations, estimated cost, and expected update frequency.

A dataset should not become automatically fetchable merely because its API responds to a browser request.

**Outputs:** `source_system`, `source_dataset`, access-review decision, manifest version.

### **Step 2 — Acquire a reproducible source snapshot**

**Concept:** An ingestion is a versioned data acquisition event, not simply a Python script that downloads records.

For GIS sources, retrieve records using an approved bulk export or an authorized, paginated API workflow. Use a deterministic order and retain the request parameters used to obtain the data.

For spreadsheets, record the exact uploaded artifact, workbook sheets, upload origin, and publication date when available.

For documents, store the original PDF or other source artifact together with its registry or deed-reference metadata.

**Outputs:** Raw file/object, acquisition timestamp, source metadata and retrieval log.

### **Step 3 — Compute content identity**

**Concept:** A cryptographic hash helps distinguish identical source payloads from changed content.

Compute SHA-256 for each original artifact and a separate content fingerprint for the overall dataset version. Sort records deterministically before computing record-set fingerprints.

For unchanged input and mapping versions, a repeated ingestion should resolve to the same version instead of publishing duplicate canonical records.

**Outputs:** `input_fingerprint`, per-record hashes, ingestion run identifier.

### **Step 4 — Parse into staging**

**Concept:** Staging is the boundary between external representations and your internal model.

For example, a county GIS field named `DEEDEDACREAGE` should become a typed observation, not a permanent field on every property entity.

Use Pydantic models to parse data, preserve original strings and capture validation failures.

A staged parcel record might look like:

```

{
  "source_dataset_id": "ga_gwinnett_parcels",
  "source_record_id": "example-source-uuid",
  "jurisdiction_fips": "13135",
  "identifiers": {
    "pin": "0123A001",
    "taxpin": null,
    "lrsn": null
  },
  "address": {
    "raw": "1250 EXAMPLE COMMERCE DR"
  },
  "measurements": {
    "deeded_acres": 2.75,
    "calculated_acres": 2.71
  },
  "geometry": {
    "format": "geojson",
    "srid": 4326,
    "coordinates_reference": "staged-geometry-object"
  },
  "source_state": "staged"
}

```

The identifier, address and measurements above are synthetic examples, not retrieved Gwinnett records.

### **Step 5 — Validate records**

Validation should operate at three levels.

| Level      | Examples                                                              | Failure behavior                     |
| ---------- | --------------------------------------------------------------------- | ------------------------------------ |
| Structural | Missing required fields, invalid data types, malformed JSON           | Reject or quarantine record          |
| Semantic   | Invalid APN, negative acreage, invalid geometry, unsupported SRID     | Quarantine or flag according to rule |
| Relational | Duplicate current parcel, ambiguous owner match, conflicting identity | Block affected canonical promotion   |

For geometry, use PostGIS `ST_IsValid`, `ST_IsValidReason` and `ST_Transform`. `ST_MakeValid` should only be applied through an explicit repair policy, with original geometry retained. The official PostGIS reference documents these validation and transformation functions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://postgis.net\&sz=32)

PostGIS



Do not treat assessor acreage and GIS-calculated acreage as interchangeable. Their discrepancies may reflect different measurement approaches, not corrupt data.

### **Step 6 — Resolve canonical identities**

**Concept:** Entity resolution determines whether a source record corresponds to an existing real-world entity.

The first release should rely heavily on deterministic keys and explicit matching rules rather than an LLM.

For Gwinnett parcels, use this precedence:

| Priority | Matching method                                                    | Result                             |
| -------- | ------------------------------------------------------------------ | ---------------------------------- |
| 1        | Existing source identifier mapping to known internal parcel UUID   | Reuse parcel                       |
| 2        | Exact normalized `PIN` within county FIPS                          | Match if unambiguous               |
| 3        | Confirmed alternate identifier mapping, such as `TAXPIN` or `LRSN` | Match with verified correspondence |
| 4        | Spatial overlap plus address agreement                             | Candidate requiring review         |
| 5        | Fuzzy address or owner-name similarity                             | Research candidate only            |

A source identifier that points to two competing active parcel records is an integrity problem. It must not be silently resolved by choosing the first result.

### **Step 7 — Construct evidence-backed assertions**

For every accepted observation, create a claim with its supporting source.

Examples:

- Parcel `P` has source-reported deeded acreage of `2.75` on snapshot date `D`.
- County assessor record `R` lists organization `O` as the tax-record owner of parcel `P`.
- State registry entry `S` identifies organization `O` under registration number `N`.
- Deed record `T` names organization `O` as a grantee on a particular instrument.

These are separate claims. The system must not infer that the corporation's registered agent personally owns the property.

### **Step 8 — Publish atomically**

**Concept:** Data publishing should be a transactionally consistent promotion from staging into the authoritative data model.

A successful publication must write the canonical record changes, geometry versions, identity mappings, claims, supporting evidence links, and publication audit event together.

If any required operation fails, the transaction must roll back.

The raw snapshot remains available so the failed publication can be diagnosed and replayed.

### **Step 9 — Reconcile against the previous version**

Compare current and preceding snapshots to detect:

- New or removed parcel records.
- Changed geometries.
- Changed ownership or mailing information.
- Changed assessments.
- Conflicting identifiers.
- Records no longer present in the source.

An absent record in a new extract does not automatically mean the parcel has been legally retired. It may indicate a partial export or acquisition failure. The system should only mark a parcel retired after applicable reconciliation rules establish that interpretation.

### **Step 10 — Publish dataset health metrics**

Each completed run should expose its acquisition source, exact input version, processing counts, rejected records, warnings, canonical changes, and unresolved conflicts.

An ingestion run is complete only when it has a reproducible result and its quality gates have been evaluated.

## **6. Entity resolution and conflict policies**

There are two identity-resolution problems, and they should not share the same matching strategy.

### **Parcel identity resolution**

Parcel matching is primarily deterministic. The strongest keys are jurisdiction-specific assessor identifiers and explicitly maintained source mappings.

The platform should preserve:

- Original identifier, including punctuation and leading zeros.
- Normalized identifier.
- Identifier type (`PIN`, `TAXPIN`, `LRSN`, provider ID).
- Issuing jurisdiction or source.
- First and last observation.
- Current or historical designation.

A parcel split should produce appropriate new parcel identities and documented predecessor/successor relationships. It should not overwrite the historical identity of the original parcel.

### **Organization identity resolution**

Corporate names require a different process because many legal entities can share similar names.

For example, these are not necessarily the same company:

- Peachtree Commercial Holdings LLC
- Peachtree Commercial Holdings II LLC
- Peachtree Holdings LLC

A suggested matching policy:

| Evidence                                                                 | Automatic treatment                     |
| ------------------------------------------------------------------------ | --------------------------------------- |
| Same authoritative registry ID and jurisdiction                          | Deterministic match                     |
| Verified historical legal-name change tied to same registration          | Deterministic match                     |
| Same exact normalized name, same jurisdiction, no conflicting candidates | Candidate unless independently resolved |
| Same mailing address or registered agent                                 | Relationship clue, not entity identity  |
| Fuzzy name match alone                                                   | Candidate only                          |
| LLM-generated relationship                                               | Unverified proposal only                |

**Critical invariant:** Two entities should not be automatically merged solely because they share an address, registered agent, attorney, telephone number or partial name.

### **Conflicting claims**

When credible records disagree, the system should preserve both observations.

For instance:

| Source            | Assertion                                                          |
| ----------------- | ------------------------------------------------------------------ |
| Assessor snapshot | Example Property Holdings LLC is listed as tax-record owner        |
| Recorded deed     | Example Acquisition LLC is the named grantee on a later instrument |
| State registry    | Example Property Holdings LLC remains active                       |

The appropriate action is to create a discrepancy for review, not infer that one LLC owns the other or that the newest document necessarily establishes current title.

The evidence model should be capable of storing source-specific facts without forcing every fact into one universal "truth" field.

## **7. Quality assurance and acceptance contracts**

Data quality should be measured both at the individual-record level and for the dataset as a whole.

### **7.1 Data quality metrics**

| Metric                                                | Proposed acceptance target |
| ----------------------------------------------------- | -------------------------- |
| Source records with stored provenance                 | 100%                       |
| Canonical parcels with jurisdiction identifiers       | 100%                       |
| Published current geometry passing PostGIS validation | 100%                       |
| Duplicate active parcel identities introduced         | 0                          |
| Ambiguous entity matches automatically verified       | 0                          |
| Unresolved acquisition errors silently ignored        | 0                          |
| Repeated identical import creating duplicate records  | 0                          |
| Published claims without required source support      | 0                          |
| Incorrect cross-tenant data exposure                  | 0                          |

These are engineering acceptance criteria. Coverage metrics, such as how many records contain usable addresses or assessor ownership values, should be measured and reported rather than given arbitrary guarantees.

### **7.2 Mandatory tests**

**Data foundation test suite**

T01 — Repeated import

Identical source data does not create duplicate canonical records

T02 — Identifier normalization

Leading zeros and original PIN formats are preserved

T03 — Invalid polygon

Invalid geometry is quarantined without silent correction

T04 — Source conflict

Competing ownership claims remain distinguishable

T05 — LLC ambiguity

Same-name or shared-agent organizations are not automatically merged

T06 — Historical preservation

Changed geometry creates a new version

T07 — Partial import

Incomplete snapshot does not cause mass parcel retirement

T08 — Transactional rollback

Failed publication leaves no partial canonical changes

T09 — Evidence lineage

Every published claim resolves to a retained source

T10 — Source authorization

Unapproved automated acquisition is blocked

T11 — Source schema change

Unexpected source fields or types trigger mapping review

T12 — Tenant security

Customer-private information cannot cross organization boundaries

0 / 12 marked complete

&#x20;Copy tests

The benchmark dataset should include synthetic failure cases and a manually reviewed sample of genuine county records. Synthetic fixtures test known edge cases; real records test integration assumptions.

## **8. Engineering implementation sequence**

With the domain and provisioning contracts established, I would implement M0 in five work packages. These packages are sequential where dependencies exist, although the source-rights review can proceed independently.

**Package 1 — Database foundation**

Establish PostgreSQL/PostGIS, SQLAlchemy models, Alembic migrations, UUID conventions, database constraints, schemas and repository interfaces.

**Deliverable:** A database that can be created from scratch and migrated consistently.

**Package 2 — Source contract framework**

Implement Pydantic manifest schemas, source registration, acquisition authorization checks, raw artifact storage, ingestion-run state tracking and checksum utilities.

**Deliverable:** A common interface for all future source adapters.

**Package 3 — Gwinnett parcel loader**

Build the approved export/ingestion workflow, spatial transformer, identifier normalization, staging validator and parcel publisher.

**Deliverable:** Real, source-backed parcel records queryable from PostGIS.

**Package 4 — Ownership and assessment enrichment**

Inspect the current assessor export, define its verified field mapping, match ownership data to parcels, construct parties and ownership claims, and quarantine ambiguities.

**Deliverable:** Parcels enriched with assessor-listed owners, assessment observations and traceable provenance.

**Package 5 — Reconciliation and validation**

Implement idempotency, geometry versioning, change detection, source health reports, benchmark fixtures and automated quality tests.

**Deliverable:** A repeatable, auditable data ingestion foundation that satisfies the acceptance criteria.

### **Suggested repository structure**

```

cre-intelligence/
├── apps/
│   └── web/                       # Later: Next.js
├── services/
│   ├── api/
│   │   └── app/
│   │       ├── core/
│   │       ├── provenance/
│   │       ├── evidence/
│   │       ├── operations/
│   │       └── database/
│   └── ingestion/
│       ├── connectors/
│       │   ├── arcgis/
│       │   ├── spreadsheets/
│       │   └── documents/
│       ├── transforms/
│       ├── validators/
│       ├── resolution/
│       └── publishing/
├── contracts/
│   ├── manifests/
│   │   ├── gwinnett_parcels.yaml
│   │   └── gwinnett_ownership.yaml
│   ├── schemas/
│   └── dictionaries/
├── database/
│   └── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── spatial/
│   └── fixtures/
├── docs/
│   ├── architecture/
│   ├── data-sources/
│   └── decisions/
└── infrastructure/

```

This is a proposed structure, not a repository that has already been created.

## **9. Remaining decisions and blockers**

A few items cannot be finalized responsibly without actual source files, usage terms or implementation testing.

| Item                                      | Current state     | Resolution                                                            |
| ----------------------------------------- | ----------------- | --------------------------------------------------------------------- |
| Gwinnett parcel schema                    | Verified          | Confirm transformation and ingestion behavior with a permitted sample |
| Gwinnett ownership workbook schema        | Uninspected       | Download current ZIP and inspect sheet structure and identifiers      |
| GIS and ownership commercial usage rights | Not established   | Review applicable terms and request clarification if necessary        |
| Automated GSCCCA access                   | Not established   | Determine permitted access method and licensing                       |
| Automated Georgia SOS access              | Not established   | Use authorized/manual intake until confirmed                          |
| Parcel normalization function             | Design defined    | Test real Gwinnett identifier edge cases                              |
| Property grouping rules                   | Partially defined | Establish how parcels become commercial asset groupings               |
| Ownership claim arbitration               | Design defined    | Validate on conflicting real-world records                            |
| Production storage/deployment             | Open              | Choose after initial data-volume and security testing                 |

None of these blockers requires changing the overall architecture. They are deliberate dependencies in the provisioning plan.

## **10. Definition of done for M0**

The **Data Foundation milestone** is complete when the following scenario works reproducibly:

A permitted Gwinnett parcel snapshot is ingested. Every accepted record receives a stable internal parcel identity, a validated geometry, a source reference, and preserved original identifiers. A separately imported ownership snapshot is matched to parcels without inventing relationships. Re-running the same inputs creates no duplicate canonical entities. Changed data produces versioned observations and evidence-backed claims. Ambiguous or invalid records appear in a review queue, and the entire ingestion run generates a quality report.

This is the first meaningful technical foundation for the broader CRE platform.

### **Project status**

| Deliverable                      | Status                         |
| -------------------------------- | ------------------------------ |
| Canonical domain model           | Designed — initial SQL drafted |
| Provisioning architecture        | Designed                       |
| Gwinnett parcel source discovery | Verified                       |
| Source manifests                 | Drafted                        |
| Identity and evidence policies   | Defined                        |
| Actual database migrations       | Not executed                   |
| Source imports                   | Not executed                   |
| End-to-end quality tests         | Not executed                   |

The next implementation action is **Package 1: create the PostgreSQL/PostGIS schema and Alembic migration structure**, followed by a controlled import of the verified Gwinnett parcel dataset. This will turn the data contracts into a testable foundation before introducing the LLM investigation engine.