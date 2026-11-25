# **CRE Intelligence & Operations Platform**

MVP Product Specification · Version 1.0 · November 22, 2026

## **1. Executive product definition**

**Product vision:** Build an AI-native commercial real estate operating platform that transforms fragmented property records, corporate ownership information, geospatial data, financial analysis, and business communications into a unified, actionable workspace.

The platform should serve commercial brokers, investors, developers, acquisition teams, and asset managers through a shared property intelligence foundation rather than separate applications for every CRE discipline.

The defining capability will be an **evidence-driven research engine** that can investigate a property, trace documented LLC ownership relationships, identify appropriate business contact channels, and prepare operational next steps.

Recommended MVP structure

**Property Data Hub**

Parcels, buildings, owners, documents, transactions, zoning and spatial intelligence

**AI Research Engine**

Ownership investigation, document extraction, evidence reconciliation and contact discovery

**CRE Operations**

Prospects, opportunities, contacts, tasks, field activity and team workflows

**Decision Intelligence**

Comparable research, basic underwriting, risk flags and research dossiers

### **Key architectural decision**

Build a **broad platform foundation with a focused set of working operations**.

The MVP should support common workflows across CRE business functions, but it should not attempt to deliver a full property-management system, leasing system, development feasibility platform, and institutional underwriting suite simultaneously.

Instead, the first release should establish six integrated capabilities:

1. Property discovery and geospatial analysis.
2. Consolidated property and ownership records.
3. AI-powered LLC and business contact investigations.
4. Financial and physical property assessment.
5. CRE opportunity, contact and activity management.
6. Evidence-backed reports and operational research.

These capabilities share the same underlying entities and can expand into specialized modules later.

## **2. User roles and operational workflows**

| User                 | Primary goal                                  | MVP capability                                                           |
| -------------------- | --------------------------------------------- | ------------------------------------------------------------------------ |
| CRE broker           | Find property owners and secure opportunities | Search, owner investigation, verified contact routes, prospect pipeline  |
| Acquisitions analyst | Evaluate possible acquisitions                | Ownership, transaction history, property assessment, basic underwriting  |
| Developer            | Find developable commercial sites             | Parcels, acreage, land use, zoning references, environmental screening   |
| Asset manager        | Research and track owned properties           | Property portfolios, documents, notes, tasks, key operating metrics      |
| Investment principal | Evaluate and prioritize opportunities         | Reports, financial assumptions, risk flags, opportunity comparison       |
| Research associate   | Compile reliable property dossiers            | Source collection, document review, evidence verification, AI assistance |

### **Five supported end-to-end workflows**

**Workflow A — Discover and research a property**

Search an address or select a parcel on the map → resolve the property → gather assessor and transaction data → review ownership and constraints → save a property research dossier.

**Workflow B — Investigate an LLC owner**

Identify the recorded legal owner → locate matching business registrations → establish documented relationships → identify a relevant business representative → verify contact information → prepare a human-reviewed inquiry.

**Workflow C — Evaluate an opportunity**

Select a property → gather tax, property and market information → input rent and expense assumptions → calculate indicative NOI, cap rate and returns → flag missing evidence → save an analysis scenario.

**Workflow D — Run CRE operations**

Add a property to a team portfolio or prospect roster → assign research or follow-up tasks → record site visits and contact attempts → attach documents → update the opportunity stage.

**Workflow E — Produce a decision-ready report**

Combine verified property facts, financial assumptions, ownership findings and outstanding risks → generate a cited report → review or correct findings → export a shareable dossier.

All five workflows should operate on the **same canonical property record**. No duplicate research workspace should be created simply because a user switches from acquisitions to asset management.

### **Feature priority matrix**

| Capability                                 | MVP                              | Later                                           |
| ------------------------------------------ | -------------------------------- | ----------------------------------------------- |
| Interactive parcel map and property search | Full                             | Multi-state coverage                            |
| Property profiles and saved portfolios     | Full                             | Complex portfolio analytics                     |
| Ownership, LLC and contact research        | Full                             | Expanded corporate data coverage                |
| Source citations and research history      | Full                             | Continuous data-change monitoring               |
| Prospecting, tasks and activity notes      | Full                             | Advanced CRM automation                         |
| Basic financial scenario analysis          | Full                             | Full acquisition underwriting                   |
| Zoning and environmental screening         | Basic                            | Automated development feasibility               |
| Leasing and tenant information             | Uploaded/manual                  | Licensed lease comps and full lease management  |
| Asset management                           | Portfolio records and tasks      | Budgeting, accounting and performance reporting |
| Automated outreach                         | Human-approved drafts            | Policy-controlled integrated messaging          |
| Broker/agency-of-record data               | Manual or sourced when available | Industry-specific integrations                  |

This keeps the MVP operationally useful across CRE functions while respecting the difference between a broad software foundation and a fully developed vertical product.

## **3. Data provisioning and acquisition strategy**

This is the most important prerequisite. The platform cannot provide reliable research if its source records are incomplete, inconsistent, stale, or legally unavailable for the intended use.

I recommend starting with **Gwinnett County, Georgia**, then adding Fulton County after the first jurisdiction passes data-quality testing. The data model should be nationwide-ready even though initial coverage is local.

### **3.1 Source inventory**

| Data source                                                                                                                                                                  | Content                                                          | MVP ingestion                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------ |
| [Gwinnett GIS Open Data](https://gcgis-gwinnettcountyga.hub.arcgis.com/?utm_source=chatgpt.com)                                                                              | Parcels, boundaries, spatial layers                              | Download/API where permitted         |
| [County GIS / assessment links](https://www.gwinnettcounty.com/government/departments/information-technology-services/geographic-systems/gis-browser?utm_source=chatgpt.com) | Parcel and ownership reference                                   | County connector                     |
| [Georgia GSCCCA](https://www.gsccca.org/learn/search-systems/real-estate-index?utm_source=chatgpt.com)                                                                       | Deeds, transactions, liens, plats                                | Authorized lookup or licensed access |
| [Georgia SOS eCorp](https://ecorp.sos.ga.gov/?utm_source=chatgpt.com)                                                                                                        | Entity registration, agents, officer information where disclosed | Registry investigation connector     |
| [Census Geocoder](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html?utm_source=chatgpt.com)                                                              | Address coordinates and census geography                         | Public REST API                      |
| [FEMA flood data](https://www.fema.gov/flood-maps/national-flood-hazard-layer?utm_source=chatgpt.com)                                                                        | Flood-hazard geography                                           | Public geospatial data               |
| [EPA ECHO](https://echo.epa.gov/tools/web-services?utm_source=chatgpt.com)                                                                                                   | Environmental compliance and regulated facilities                | Public REST services                 |
| [Regrid](https://support.regrid.com/docs/getting-started-api?utm_source=chatgpt.com)                                                                                         | Standardized nationwide parcels, tax, owner attributes           | Optional licensed API                |
| [LightBox](https://developer.lightboxre.com/apis/parcels?utm_source=chatgpt.com)                                                                                             | Parcel geometry, property attributes, ownership                  | Alternative licensed API             |
| Customer uploads                                                                                                                                                             | Rent rolls, offering memoranda, leases, contacts, financials     | Controlled document/CSV ingestion    |

The county GIS resources support property lookup and downloadable spatial datasets, while the GSCCCA indexes recorded instruments across Georgia. Georgia's business registry offers searches for entities and associated corporate records. These are distinct sources with different evidentiary functions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.gwinnettcounty.com\&sz=32)

Gwinnett+2



Regrid has address, owner, APN and spatial lookup capabilities; LightBox also provides a standardized parcel API. Both are potential commercial enrichment providers, but redisplay, caching, retention, bulk access and use in a multi-tenant product must be established contractually before integration.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://support.regrid.com\&sz=32)

Regrid Support+1



**Important:** A publicly viewable website does not imply permission for automated collection or commercial redistribution. If a registry offers no supported bulk interface, the MVP should support authorized manual research and document import rather than assuming scraping is permitted.

### **3.2 Provisioning pipeline**

### **Canonical data pipeline**

**Source connectors**

County GIS · Registry · Deeds · Public APIs · Licensed data · Uploads

**Raw immutable storage**

Original records, documents, snapshots, metadata and checksums

**Staging and quality validation**

Schema mapping, geometry validation, null checks, quarantine

**Identity and relationship resolution**

Parcel matching, address normalization, entities, ownership claims

**Canonical PostgreSQL + PostGIS**

Properties · Parcels · Organizations · Contacts · Evidence · Spatial layers

GIS App

AI Research

Operations

The provisioning contract should require each connector to perform acquisition, validation and publishing separately. Raw data must remain distinguishable from enriched or human-corrected data.

### **3.3 Source manifest contract**

Every integration should have a declarative manifest. This allows the ingestion engine to operate consistently across counties and vendors.

Example proposed manifest:

```

source_id: gwinnett_parcels
source_type: county_gis
jurisdiction:
  state: GA
  county_fips: "135"

acquisition:
  method: approved_bulk_export
  resource: configured_source_url
  format: geojson
  schedule: manual_initially

mapping:
  parcel_id: configured_apn_field
  geometry: configured_geometry_field
  owner_name: configured_owner_field
  situs_address: configured_address_field

quality:
  required:
    - parcel_id
    - geometry
  spatial_reference: EPSG:4326
  quarantine_invalid_geometry: true

governance:
  license_status: pending_review
  redistribution_allowed: unknown
  raw_retention: policy_pending
  attribution_required: pending_review
  credential_reference: null

```

The field names and permissions are intentionally unresolved until the actual dataset and terms are inspected. A manifest must never imply approval that has not been established.

### **3.4 Data integration rules**

The ingestion service should guarantee:

- **Idempotence:** Re-running a job with the same source version does not create duplicate records.
- **Lineage:** Every canonical value can be traced to source records and ingestion runs.
- **Temporal accuracy:** Preserve the source's effective date separately from the date it was retrieved.
- **Conflict preservation:** Conflicting sources produce competing claims for review, not silent overwrites.
- **Schema evolution:** Provider field changes trigger validation and mapping review.
- **Quality quarantine:** Invalid geometry, unsupported identifiers and ambiguous matches do not automatically enter production records.

For example, if an assessor says an LLC owns a parcel but a newer recorded deed names a different company, the platform should flag an ownership discrepancy. It should not blindly choose the latest fetched record.

### **3.5 Initial data targets**

These are proposed engineering targets, not claims about existing data access.

| Dataset                        | Initial target | Purpose                                  |
| ------------------------------ | -------------- | ---------------------------------------- |
| Parcel/property samples        | 1,000          | Geometry, search, record normalization   |
| Manually validated parcels     | 100            | Parcel identity and matching benchmark   |
| LLC ownership investigations   | 30             | Entity-resolution evaluation             |
| Deed/registry document samples | 100            | Extraction and provenance tests          |
| Business contact cases         | 30             | Contact-role and evidence evaluation     |
| Financial test scenarios       | 25             | Underwriting calculation verification    |
| Operational opportunities      | 50             | Task, workflow and authorization testing |

Use public, licensed, synthetic or customer-authorized information as appropriate. Include intentionally ambiguous and conflicting records to test how the platform behaves when certainty is impossible.

## **4. Canonical domain model**

This is the architectural center of the entire system.

The critical distinction is that a **parcel is not the same thing as a property, a building, an ownership entity, or an investment opportunity**.

A shopping center may occupy multiple parcels. A single parcel may contain several buildings. Multiple business entities may hold different interests or operating responsibilities. One property may also be involved in several acquisition or leasing opportunities over time.

### **4.1 Core entities**

| Domain     | Entity                  | Important fields                                               |
| ---------- | ----------------------- | -------------------------------------------------------------- |
| Geography  | `jurisdiction`          | ID, state, county FIPS, municipality                           |
| Geography  | `address`               | Normalized address, location, geocode quality                  |
| Property   | `property`              | ID, name, asset class, location, lifecycle                     |
| Property   | `parcel`                | Jurisdiction, APN, geometry, acreage, source                   |
| Property   | `building`              | Building ID, property ID, area, use, year built                |
| Property   | `space`                 | Building, suite/unit, area, occupancy                          |
| Property   | `property_parcel`       | Property–parcel association and validity dates                 |
| Ownership  | `party`                 | Common identity for person or organization                     |
| Ownership  | `legal_entity`          | Party ID, legal name, jurisdiction, registry ID, entity status |
| Ownership  | `party_relationship`    | Subject, object, relationship type, evidence, valid period     |
| Ownership  | `ownership_record`      | Property/parcel, legal owner, effective interval, source       |
| Contacts   | `contact_point`         | Party, business phone/email, source, verification state        |
| Contacts   | `contact_role`          | Party, company/property, role, source, validity                |
| Sources    | `source_record`         | Provider ID, source URI, checksum, retrieval metadata          |
| Sources    | `evidence_claim`        | Subject, predicate, value, source, confidence, review state    |
| Sources    | `document`              | File, document type, access permissions, version               |
| Finance    | `financial_observation` | Metric, value, period, currency, origin                        |
| Finance    | `analysis_scenario`     | Property, assumption set, model version, outputs               |
| Operations | `portfolio`             | Workspace, purpose, properties                                 |
| Operations | `opportunity`           | Property, type, stage, assigned team                           |
| Operations | `activity`              | Task, note, site visit, contact attempt, outcome               |
| AI         | `investigation`         | Subject, objective, status, research limits                    |
| AI         | `investigation_step`    | Tool call, inputs, outputs, evidence references                |

For property ownership, the schema should support multiple interests, historical changes and source disagreement. A recorded grantee is not automatically the ultimate beneficial owner.

### **4.2 Relationships**

\#chatgpt-mermaid-\_r_ui\_{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;fill:rgb(191, 189, 182);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_ui\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_ui\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_ui\_ .error-icon{fill:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_ui\_ .error-text{fill:rgb(191, 189, 182);stroke:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_ui\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_ui\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_ui\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_ui\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_ui\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_ui\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_ui\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_ui\_ .marker.cross{stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_ui\_ svg{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;}#chatgpt-mermaid-\_r_ui\_ p{margin:0;}#chatgpt-mermaid-\_r_ui\_ .entityBox{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_ui\_ .relationshipLabelBox{fill:rgba(191, 189, 182, 0.03);opacity:0.7;background-color:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_ui\_ .relationshipLabelBox rect{opacity:0.5;}#chatgpt-mermaid-\_r_ui\_ .labelBkg{background-color:rgba(191, 189, 182, 0.5);}#chatgpt-mermaid-\_r_ui\_ .edgeLabel{background-color:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_ui\_ .edgeLabel .label rect{fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_ui\_ .edgeLabel .label text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_ui\_ .edgeLabel .label{fill:rgb(108, 163, 252);font-size:14px;}#chatgpt-mermaid-\_r_ui\_ .label{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_ui\_ .edge-pattern-dashed{stroke-dasharray:8,8;}#chatgpt-mermaid-\_r_ui\_ .node rect,#chatgpt-mermaid-\_r_ui\_ .node circle,#chatgpt-mermaid-\_r_ui\_ .node ellipse,#chatgpt-mermaid-\_r_ui\_ .node polygon{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_ui\_ .relationshipLine{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;fill:none;}#chatgpt-mermaid-\_r_ui\_ .marker{fill:none!important;stroke:rgba(191, 189, 182, 0.498)!important;stroke-width:1;}#chatgpt-mermaid-\_r_ui\_ [data-look=neo].labelBkg{background-color:rgba(191, 189, 182, 0.5);}#chatgpt-mermaid-\_r_ui\_ .node .neo-node{stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_ui\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_ui\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node .neo-line path{stroke:rgb(108, 163, 252);filter:none;}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_ui\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_ui\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_ui\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_ui\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_ui\_ :root{--mermaid-font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;}PROPERTYPROPERTY_PARCELPARCELBUILDINGSPACEOWNERSHIP_RECORDPARTYPARTY_RELATIONSHIPCONTACT_POINTOPPORTUNITYACTIVITYINVESTIGATIONINVESTIGATION_STEPEVIDENCE_CLAIMSOURCE_RECORDincludesbelongs_tocontainscontainshasrecorded_as_ownersubjecthastracked_ingeneratesresearched_byrecordssupported_by

This is a conceptual ER diagram; the actual migration set should also include tenant ownership, access controls, source-to-canonical mapping tables, and temporal constraints.

### **4.3 Data modeling decisions to enforce**

**Identity:** Use internal UUIDs for canonical entities. A parcel's natural identity should include its jurisdiction and assessor identifier; an APN is not globally unique and can change after parcel splits or consolidations.

**Ownership:** Store property ownership separately from organization-to-organization or person-to-organization relationships. Use explicitly typed relationships such as `recorded_owner`, `registered_agent`, `disclosed_manager`, `asset_manager`, and `possible_affiliate`.

**Evidence:** Model a claim independently from the currently selected value. A human correction should produce a reviewable decision rather than deleting the contradictory evidence.

**Temporal data:** Use `valid_from` and `valid_to` for real-world applicability and `observed_at` for when the system learned the information. This allows historical reconstruction.

**Financial data:** Store source amounts separately from modeled estimates. For instance, an assessor valuation, broker opinion of value, and internal DCF valuation are three different observations.

**Tenant isolation:** Customer-owned portfolios, contacts, notes, uploaded documents and opportunities must carry organization-level authorization. Shared licensed datasets must be separated according to provider redistribution rights.

## **5. LLC ownership and contact investigation engine**

This should be a first-class subsystem, not merely a prompt attached to a property profile.

### **5.1 Investigation contract**

An investigation begins with a structured request:

```

{
  "property_id": "property-uuid",
  "objective": "find_business_contact",
  "preferred_roles": [
    "authorized_owner_representative",
    "asset_manager",
    "acquisitions_contact",
    "property_manager"
  ],
  "research_mode": "approved_sources_only",
  "allow_external_outreach": false,
  "require_evidence": true,
  "max_external_requests": 20
}

```

These are proposed application fields. They allow the backend to validate an investigation's permitted activities before an LLM executes any research.

### **5.2 Investigation execution**

1. **Resolve the recorded owner**

   Query property and deed records. Record the exact legal name, deed reference, effective date and source. If ownership differs across sources, create a conflict requiring resolution.
2. **Resolve the business entity**

   Normalize the legal name and search the relevant state registry. Match using jurisdiction, registration ID, legal name, address and other disclosed identifiers. Reject ambiguous automatic matches.
3. **Build the relationship graph**

   Extract disclosed managers, officers, registered agents, corporate affiliations and documented ownership relationships. Keep relationships explicitly typed and dated.
4. **Find appropriate business representatives**

   Search authorized public corporate information, company websites, property management listings and licensed contact providers for individuals or organizational channels relevant to the property.
5. **Validate contact routes**

   Confirm the business association and professional role independently from the channel. A valid general-office number does not prove that a particular person owns the property.
6. **Select an outcome**

   Return a verified business contact, a candidate requiring review, an organizational inquiry route, or an unresolved investigation. The agent must be allowed to abstain.
7. **Prepare next steps**

   Create a contact-verification task or an outreach draft for review. Only an authorized user may approve external communication in the MVP.

### **5.3 Identity versus relationship versus reachability**

I recommend representing these as three independent evaluations.

| Dimension            | Question                                                          |
| -------------------- | ----------------------------------------------------------------- |
| Entity resolution    | Is this the correct LLC or legal entity?                          |
| Role verification    | Does this party have a documented role relevant to the property?  |
| Contact verification | Is this an authentic, appropriate business communication channel? |

Do not combine them into one opaque "confidence = 95%" value.

A person can be accurately identified as a registered agent but still be inappropriate for acquisition outreach. Equally, a company may publish a working telephone number while the identity of its ultimate owners remains unknown.

The Georgia Secretary of State explicitly explains that registered agents may not be owners or officers. Additionally, FinCEN's final rule effective August 14, 2026 exempts U.S. companies from beneficial-ownership reporting, so this platform should not depend on access to a comprehensive beneficial-owner registry.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://sos.ga.gov\&sz=32)

Georgia Secretary of State+2



### **5.4 Evidence and verification states**

| State          | Definition                                                     | Permitted presentation                       |
| -------------- | -------------------------------------------------------------- | -------------------------------------------- |
| `verified`     | Direct, authoritative evidence supports the specific assertion | Display as verified with citation            |
| `corroborated` | Multiple sufficiently independent sources support it           | Display with supporting evidence and caveats |
| `candidate`    | Plausible but material ambiguity remains                       | Require review; do not present as fact       |
| `conflicted`   | Credible evidence materially disagrees                         | Display discrepancy                          |
| `stale`        | Previously supported but beyond the review policy              | Require revalidation                         |
| `unresolved`   | Insufficient evidence                                          | Explicitly report unknown                    |

A registered agent's name appearing in an official registry may be verified as a registered agent, but the existence of a beneficial ownership relationship would remain unresolved unless separately supported.

For ranking contact routes, use role relevance, evidence quality, recency and channel validity. Any numeric score should be an internal prioritization heuristic until calibrated against independently labeled investigation cases.

### **5.5 What happens if no contact can be found?**

The agent should return a structured unresolved result with the searches attempted, coverage gaps, the best available organizational contact route, and recommended next actions.

For example:

**Investigation outcome: no verified decision-maker**

Legal owner: Example Commerce Holdings LLC

Registry match: Verified

Beneficial owner: Undetermined

Relevant business contact: General corporate inquiry channel identified

Proposed next action

Draft a professional inquiry requesting the appropriate representative for a commercial property matter. Require review before any communication is sent.

Hypothetical example; not an actual company or completed investigation.

That unresolved outcome is valuable because it prevents unsubstantiated contact attribution and directs the research associate toward the next permissible action.

### **5.6 Outreach subsystem**

The MVP should support four distinct activities: contact discovery, contact verification, outreach drafting, and approved activity logging.

Outbound messaging should be permission-gated, with opt-out/suppression controls, sending identity, required disclosures and a full audit history. The FTC confirms that CAN-SPAM applies to business-to-business commercial email, not only consumer campaigns.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.ftc.gov\&sz=32)

Federal Trade Commission



I would exclude autonomous cold calling, inferred personal telephone numbers, unsupervised email campaigns, and mass harvesting of personal contacts from the initial product.

## **6. AI architecture and orchestration**

The LLM should operate as a **reasoning and extraction layer above deterministic services**, rather than becoming the source of truth.

\#chatgpt-mermaid-\_r_vl\_{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;fill:rgb(191, 189, 182);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_vl\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_vl\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_vl\_ .error-icon{fill:rgba(191, 189, 182, 0.03);}#chatgpt-mermaid-\_r_vl\_ .error-text{fill:rgb(191, 189, 182);stroke:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_vl\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_vl\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_vl\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_vl\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_vl\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_vl\_ .marker.cross{stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_vl\_ svg{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:14px;}#chatgpt-mermaid-\_r_vl\_ p{margin:0;}#chatgpt-mermaid-\_r_vl\_ .label{font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .cluster-label text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .cluster-label span{color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_vl\_ .label text,#chatgpt-mermaid-\_r_vl\_ span{fill:rgb(191, 189, 182);color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .node rect,#chatgpt-mermaid-\_r_vl\_ .node circle,#chatgpt-mermaid-\_r_vl\_ .node ellipse,#chatgpt-mermaid-\_r_vl\_ .node polygon,#chatgpt-mermaid-\_r_vl\_ .node path{fill:rgb(0, 58, 56);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .rough-node .label text,#chatgpt-mermaid-\_r_vl\_ .node .label text,#chatgpt-mermaid-\_r_vl\_ .image-shape .label,#chatgpt-mermaid-\_r_vl\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_vl\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .rough-node .label,#chatgpt-mermaid-\_r_vl\_ .node .label,#chatgpt-mermaid-\_r_vl\_ .image-shape .label,#chatgpt-mermaid-\_r_vl\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_vl\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_vl\_ .root .anchor path{fill:rgba(191, 189, 182, 0.498)!important;stroke-width:0;stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_vl\_ .arrowheadPath{fill:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_vl\_ .edgePath .path{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .flowchart-link{stroke:rgba(191, 189, 182, 0.498);fill:none;}#chatgpt-mermaid-\_r_vl\_ .edgeLabel{background-color:rgb(16, 20, 28);text-align:center;}#chatgpt-mermaid-\_r_vl\_ .edgeLabel p{background-color:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_vl\_ .edgeLabel rect{opacity:0.5;background-color:rgb(16, 20, 28);fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_vl\_ .labelBkg{background-color:rgba(16, 20, 28, 0.5);}#chatgpt-mermaid-\_r_vl\_ .cluster rect{fill:rgba(191, 189, 182, 0.03);stroke:rgba(191, 189, 182, 0.082);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .cluster text{fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ .cluster span{color:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;font-size:12px;background:rgba(191, 189, 182, 0.03);border:1px solid rgba(191, 189, 182, 0.082);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_vl\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(191, 189, 182);}#chatgpt-mermaid-\_r_vl\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_vl\_ .icon-shape,#chatgpt-mermaid-\_r_vl\_ .image-shape{background-color:rgb(16, 20, 28);text-align:center;}#chatgpt-mermaid-\_r_vl\_ .icon-shape p,#chatgpt-mermaid-\_r_vl\_ .image-shape p{background-color:rgb(16, 20, 28);padding:2px;}#chatgpt-mermaid-\_r_vl\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_vl\_ .image-shape .label rect{opacity:0.5;background-color:rgb(16, 20, 28);fill:rgb(16, 20, 28);}#chatgpt-mermaid-\_r_vl\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_vl\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_vl\_ .node .neo-node{stroke:rgb(108, 163, 252);}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_vl\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_vl\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node .neo-line path{stroke:rgb(108, 163, 252);filter:none;}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_vl\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_vl\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_vl\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_vl\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_vl\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(99, 241, 237);}#chatgpt-mermaid-\_r_vl\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(99, 241, 237);}#chatgpt-mermaid-\_r_vl\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_vl\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_vl\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(16, 20, 28);stroke:rgb(108, 163, 252);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .node rect,#chatgpt-mermaid-\_r_vl\_ .node circle,#chatgpt-mermaid-\_r_vl\_ .node ellipse,#chatgpt-mermaid-\_r_vl\_ .node polygon,#chatgpt-mermaid-\_r_vl\_ .node path{fill:rgb(0, 58, 56);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_vl\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_vl\_ .mermaid-decision .label-container{fill:rgb(16, 20, 28);stroke:rgb(108, 163, 252);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_vl\_ .edgePaths .flowchart-link{stroke:rgba(191, 189, 182, 0.498);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_vl\_ .marker{fill:rgba(191, 189, 182, 0.498);stroke:rgba(191, 189, 182, 0.498);}#chatgpt-mermaid-\_r_vl\_ :root{--mermaid-font-family:Inter,-apple-system,"system-ui","Segoe UI",sans-serif;}CRE Web ApplicationFastAPI ServicePostgreSQL + PostGISInvestigation Job QueueResearch OrchestratorApproved Source ToolsPublic / Licensed / InternalDataSource and DocumentStorageProvider-Neutral LLMGatewayStructured FindingsEvidence and Policy ValidatorReview Required?Human ReviewPublish Sourced FindingsYesNo

### **Component choices**

| Component          | Recommended implementation                                    |
| ------------------ | ------------------------------------------------------------- |
| Frontend           | Next.js, React, TypeScript, Tailwind                          |
| Map                | MapLibre GL JS                                                |
| Backend            | FastAPI and Pydantic                                          |
| Database           | PostgreSQL with PostGIS                                       |
| Spatial search     | PostGIS GIST indexes and spatial SQL                          |
| Text search        | PostgreSQL full-text search with trigram matching             |
| Documents          | S3-compatible object storage                                  |
| Workers            | Redis + Celery when asynchronous load justifies them          |
| LLM gateway        | Provider-neutral interface with structured outputs            |
| Document retrieval | Full-text first, pgvector for semantic retrieval where useful |
| Authentication     | OIDC-compatible authentication and organization-scoped RBAC   |
| Observability      | OpenTelemetry, structured logs, investigation traces          |

MapLibre is appropriate for the parcel-first interface because it supports interactive vector layers and custom data sources without tying the rendering library to a proprietary geospatial provider. The underlying basemap and tile services still require independent licensing and cost decisions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://maplibre.org\&sz=32)

MapLibre



### **Agent capabilities**

Define a narrow set of independently testable backend tools:

| Tool                      | Function                                                   |
| ------------------------- | ---------------------------------------------------------- |
| `resolve_property`        | Match address, APN and coordinates to a canonical property |
| `query_parcel`            | Retrieve property geometry and assessor attributes         |
| `find_deeds`              | Retrieve authorized transaction or instrument references   |
| `lookup_entity`           | Resolve legal entity registration                          |
| `extract_relationships`   | Extract supported roles and relationships                  |
| `find_business_contact`   | Discover candidate professional contact channels           |
| `validate_claim`          | Check evidence support, relevance and conflicts            |
| `get_property_context`    | Assemble the canonical property research context           |
| `run_financial_analysis`  | Execute deterministic financial calculations               |
| `create_research_dossier` | Generate a structured report                               |
| `prepare_outreach`        | Produce a draft requiring approval                         |

Any source document or retrieved web page should be treated as untrusted content. Tool instructions, authentication data, system prompts and tenant-private records must not be exposed through retrieved material.

The LLM should never execute unrestricted SQL or arbitrary network requests. Route requests through typed tools with server-side access enforcement.

### **AI output format**

Every material finding should follow a structured output contract:

```

{
  "finding_type": "contact_candidate",
  "subject_id": "party-uuid",
  "assertion": "Possible asset management contact",
  "verification_state": "candidate",
  "source_record_ids": [
    "source-uuid-1",
    "source-uuid-2"
  ],
  "limitations": [
    "Property-specific authority not established"
  ],
  "recommended_action": "human_review_required"
}

```

This structure makes results testable, explainable and usable by the frontend and workflow engine without requiring users to interpret an unstructured LLM response.

## **7. CRE intelligence and financial analysis**

The MVP should have a common property profile that separates publicly obtainable information from customer-provided information and derived estimates.

### **Property intelligence tabs**

| Tab                | Data displayed                                                                  | Data availability                   |
| ------------------ | ------------------------------------------------------------------------------- | ----------------------------------- |
| Overview           | Address, parcel map, asset class, area, improvements                            | Public/verified or unknown          |
| Ownership          | Deeded owners, entity relationships, historical records, contacts               | Public, licensed and investigated   |
| Transactions       | Recorded sales, deeds, financing instruments, liens                             | Public/authorized records           |
| Site & development | Parcel shape, acreage, flood exposure, zoning references, nearby infrastructure | Public GIS and local government     |
| Financials         | Assessments, taxes, income, expenses, cap rate, NOI                             | Mix of public, uploaded and modeled |
| Leasing            | Tenants, occupancy, lease dates, rent rolls, expirations                        | Primarily customer-provided         |
| Documents          | Deeds, filings, reports, offering memoranda, leases                             | Public or uploaded                  |
| Activity           | Research tasks, site visits, communications, opportunity history                | Internal workspace                  |

### **Financial calculation engine**

The backend should perform numeric calculations directly. The LLM can explain and interpret results, but it should not generate the authoritative arithmetic.

For example:

\\[ NOI = EGI - OpEx \\]

where EGI is effective gross income and OpEx is the property's operating expenses, excluding financing costs, depreciation and income taxes.

\\[ Cap\ Rate = \frac{NOI}{Property\ Value} \\]

\\[ DSCR = \frac{NOI}{Annual\ Debt\ Service} \\]

The MVP can support income-based valuation, expense-ratio scenarios, cap-rate sensitivity, price-per-square-foot and simple cash-on-cash return calculations.

Every calculation must preserve inputs, assumptions, model version and provenance. A calculated cap rate based on hypothetical market rent must be labeled as a scenario, not an observed property fact.

## **8. Application structure and API design**

### **Proposed navigation**

**CRE Intelligence**

Application structure

Dashboard

Operations overview

Explore

Maps and property search

Properties

Records and portfolios

Ownership

Entities and contacts

Investigations

AI research and evidence

Opportunities

Pipeline and activities

Analysis

Financial scenarios

Documents

Reports and source records

The map, property list, ownership investigation, and opportunity pipeline should all link to the same property-detail view. Research activity should be recoverable from both the subject property and its associated investigation history.

### **Recommended REST API**

| Endpoint                               | Purpose                                             |
| -------------------------------------- | --------------------------------------------------- |
| `GET /v1/properties`                   | Search and filter properties                        |
| `GET /v1/properties/{id}`              | Canonical property profile                          |
| `GET /v1/parcels`                      | Parcel lookup by APN, bounding box or coordinates   |
| `GET /v1/properties/{id}/ownership`    | Recorded ownership and supported relationships      |
| `GET /v1/entities/{id}`                | Business entity information                         |
| `GET /v1/entities/{id}/relationships`  | Documented corporate and professional relationships |
| `POST /v1/investigations`              | Start controlled AI research                        |
| `GET /v1/investigations/{id}`          | Research status, evidence and findings              |
| `POST /v1/investigations/{id}/reviews` | Accept, reject or correct findings                  |
| `GET /v1/opportunities`                | List prospecting and investment opportunities       |
| `POST /v1/opportunities`               | Create an opportunity                               |
| `POST /v1/analysis-scenarios`          | Create financial analysis scenario                  |
| `POST /v1/reports`                     | Generate a dossier from verified data               |

All mutation endpoints must enforce tenant permissions, validate input, and create audit events. Long-running investigation and reporting requests should return a job identifier; progress and results can be retrieved through polling or server-sent events.

For an MVP, use asynchronous workers for ingestion, document processing and investigations. Keep property lookups and operational CRUD as straightforward synchronous API calls.

## **9. Security, data governance and operational reliability**

Because the system combines public records, potentially sensitive customer documents, and professional contact data, governance must be implemented at the beginning rather than added after launch.

| Requirement            | MVP implementation                                                    |
| ---------------------- | --------------------------------------------------------------------- |
| Organization isolation | Organization-scoped access enforced at the database/service layer     |
| Permissions            | Admin, researcher, analyst and viewer roles                           |
| Sensitive contacts     | Role-based access and source/usage restrictions                       |
| Credentials            | Dedicated secret management; no secrets in prompts                    |
| Document security      | Private object storage, scoped access, encryption                     |
| Source licensing       | Provider-specific retention and redistribution policies               |
| Evidence integrity     | Immutable source snapshots or compliant source references with hashes |
| Auditability           | Append-only security and investigation activity logs                  |
| LLM controls           | Tool allowlists, token budgets, request limits, input validation      |
| External communication | Explicit approval, suppression checks and audit history               |
| Data correction        | Reviewable corrections with historical evidence preserved             |
| Deletion               | Tenant and provider-policy-aware retention/deletion procedures        |

For the initial production pilot, I would also require automated database backups, restore testing, source health monitoring, job retries with dead-letter handling, and per-provider usage metering.

Regrid's documented billing model counts parcel records returned, including repeated lookups, so caching, deduplication and request limits are direct cost-control requirements rather than optional performance improvements.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://support.regrid.com\&sz=32)

Regrid Support



### **Proposed acceptance benchmarks**

These are engineering targets to validate, not guarantees about third-party data.

| Metric                                             | Initial target                          |
| -------------------------------------------------- | --------------------------------------- |
| Manually benchmarked parcel identity accuracy      | ≥ 98%                                   |
| Entity matches incorrectly auto-verified           | 0 in the reviewed benchmark             |
| Evidence coverage for material AI assertions       | 100%                                    |
| Unverified personal contacts presented as verified | 0                                       |
| Financial calculation accuracy                     | 100% against deterministic unit tests   |
| Tenant isolation tests                             | 100% pass                               |
| Property detail API response                       | p95 under 1 second on cached pilot data |
| Auditable investigation completion                 | 100% of investigations                  |
| Successful reconstruction of a published report    | 100% from stored input versions         |

The product should be evaluated on both successful research and **correct abstention**. Returning "unresolved" is better than fabricating a corporate relationship or contact.

## **10. Implementation priorities and milestone plan**

I would use a dependency-driven implementation sequence instead of building screens first and discovering later that the required data cannot be obtained.

**M0 — Data foundation and contracts**

Highest priority

Source inventory and licensing/access matrix

Canonical property, parcel, party and evidence schema

Raw/staging/canonical data layers

County parcel ingestion and validation

Benchmark dataset and source provenance tests

**Exit gate:** Reproducible ingestion; 100 benchmarked properties; validated identifiers, geometry and source references.

**M1 — Property Explorer**

Map search and property-detail API

Interactive map and property profile

**Exit gate:** Select a parcel, open a property record, view linked sources, and save the property to a workspace.

**M2 — Ownership Intelligence**

Legal entity matching and ownership relationships

Evidence-backed LLC investigation workflow

Contact verification and review interface

**Exit gate:** Complete an LLC research case with a verified relationship graph, sourced contact route or documented unresolved result.

**M3 — Operations and Analysis**

Portfolios, opportunities and activities

Financial scenarios and source-aware reporting

**Exit gate:** A property can be researched, analyzed, placed in a pipeline, assigned tasks, and exported in a report.

**M4 — Production pilot**

Permissions, audit, testing and pilot evaluation

**Exit gate:** Pilot users complete the five core workflows with acceptable accuracy, permissions, operational cost and reviewability.

0 of 13 planning tasks complete

&#x20;Copy checklist

## **11. MVP completion scenarios**

Before considering the MVP complete, I would require these five acceptance tests.

| Scenario                           | Expected outcome                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Known commercial property          | Address or map selection resolves the correct parcel and opens its property record                                 |
| LLC with documented representative | Investigation identifies the entity, attaches relationship evidence and proposes a relevant verified contact route |
| LLC with opaque ownership          | Investigation returns unresolved rather than inferring an owner from a registered agent or shared address          |
| Property with conflicting records  | The system preserves competing evidence and routes the discrepancy for review                                      |
| Acquisition research               | User builds a financial scenario, saves a prospect, assigns tasks and exports a cited dossier                      |

Additionally, test inaccessible sources, expired credentials, rate limits, changed registry structures, malformed documents, prompt injection in retrieved records, and conflicting tenant permissions.

A failed external request should not cause the system to invent a replacement fact. It should preserve the partial investigation and make the missing dependency visible.

## **12. Engineering decisions I would finalize now**

| Decision                    | Recommendation                                                        |
| --------------------------- | --------------------------------------------------------------------- |
| Initial geography           | Gwinnett County, Georgia                                              |
| Expansion pilot             | Fulton County, Georgia                                                |
| Product foundation          | Multi-tenant, modular monolith                                        |
| Geospatial database         | PostgreSQL + PostGIS                                                  |
| Map rendering               | MapLibre GL JS                                                        |
| AI                          | Provider-neutral, structured tool orchestration                       |
| Source acquisition          | Public/authorized sources first, commercial API optional              |
| Primary property identifier | Internal UUID, mapped to jurisdiction-specific parcel IDs             |
| Ownership graph             | Relational relationship tables initially                              |
| Search                      | PostgreSQL search and spatial indexes                                 |
| Background processing       | Worker jobs, durable execution history                                |
| Outreach                    | Verified business routes and human-approved communication             |
| Initial deployment          | Managed web/API/database infrastructure with protected object storage |
| Mobile                      | Responsive field-use interface; dedicated app later                   |

I would **not introduce Neo4j or a vector database as mandatory infrastructure** at this stage. PostgreSQL can support the initial ownership graph, spatial data, search and operational workload. A graph database becomes justified when relationship traversal complexity or performance evidence warrants one.

Likewise, local-first development is compatible with this architecture, but the shared operational platform should have a central authoritative database and access-controlled team workspace.

## **13. Recommended first engineering deliverables**

Before implementing application functionality, I would formalize five specifications:

| Deliverable                                    | Required contents                                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **01 — Domain and data contract**              | Canonical entities, relationships, primary keys, constraints, temporal semantics                 |
| **02 — Data provisioning specification**       | Source manifests, acquisition rights, schemas, ingestion, validation, reconciliation and refresh |
| **03 — Ownership investigation specification** | Agent state machine, tool interfaces, verification criteria, evidence contracts, escalation      |
| **04 — Operations specification**              | User roles, property portfolios, opportunities, activities, permission boundaries                |
| **05 — Architecture and API specification**    | Component diagram, endpoint contracts, event and job lifecycles, security, deployment and tests  |

The execution order should be **data foundation → property identity → ownership intelligence → operational workflows → financial and decision intelligence**. That ordering minimizes the risk of building an impressive interface around weak or unusable property data.

The product's defensible advantage is not the LLM itself. It is the combination of reliable CRE entity resolution, traceable research, integrated business workflows, and continuously improvable property intelligence.

**My recommended next step is to formalize the canonical schema and data provisioning contract first.** Those two specifications determine whether every later feature—mapping, LLC research, acquisition analysis, leasing, asset management and reporting—can operate on one coherent and trustworthy dataset.