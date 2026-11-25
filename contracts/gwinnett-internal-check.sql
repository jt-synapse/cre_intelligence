-- Run with psql -X -d cre_gwinnett_internal -f contracts/gwinnett-internal-check.sql
-- The operator needs read access to the tables and PostGIS. Every result is aggregate.
\set ON_ERROR_STOP on
\pset pager off
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL client_min_messages = warning;
SET LOCAL work_mem = '32MB';
-- The local Docker baseline has a small shared-memory mount. Ordinary hash joins
-- can spill to PostgreSQL temp files without allocating multi-worker shared hashes.
SET LOCAL enable_parallel_hash = off;

SELECT current_database() = 'cre_gwinnett_internal' AS private_database,
       NOT has_database_privilege('cre_runtime', current_database(), 'CONNECT') AS runtime_denied,
       NOT has_database_privilege('cre_worker', current_database(), 'CONNECT') AS worker_denied,
       NOT EXISTS (
           SELECT FROM pg_database d,
             LATERAL aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
           WHERE d.datname = current_database() AND a.grantee = 0 AND a.privilege_type = 'CONNECT'
       ) AS public_denied
\gset access_
\echo private_database=:access_private_database runtime_connect_denied=:access_runtime_denied worker_connect_denied=:access_worker_denied public_connect_denied=:access_public_denied
SELECT :'access_private_database'::boolean AND :'access_runtime_denied'::boolean
   AND :'access_worker_denied'::boolean AND :'access_public_denied'::boolean AS ok
\gset access_
\if :access_ok
\else
    DO $$ BEGIN RAISE EXCEPTION 'Private database access check failed'; END $$;
\endif

SELECT count(*) = 2 AND bool_and(enabled AND NOT shared_display AND NOT export_allowed
           AND (manifest->'rights') @> '{"status":"approved","retain_original":true,"shared_display":false,"export_allowed":false}'
           AND manifest->'rights'->'methods' = '["manual"]'::jsonb) AS ok
FROM provenance.source_dataset WHERE dataset_key IN ('gwinnett_parcels', 'gwinnett_assessor')
\gset policy_
SELECT (SELECT count(*) FROM provenance.visible_source_record WHERE dataset_key IN ('gwinnett_parcels','gwinnett_assessor')) AS source_records,
       (SELECT count(*) FROM core.visible_parcel WHERE county_fips='13135') AS parcels,
       (SELECT count(*) FROM evidence.visible_claim WHERE dataset_key IN ('gwinnett_parcels','gwinnett_assessor')) AS claims
\gset visible_
\echo private_source_policies=:policy_ok shared_sources=:visible_source_records shared_parcels=:visible_parcels shared_claims=:visible_claims

-- Reconcile the reviewed artifacts with all source rows, their original positions, the
-- canonical output and its held rows. A held-and-published row cannot mask a missing row.
WITH expected(dataset, row_count, first_pos, sha) AS (VALUES
    ('gwinnett_parcels', 309555, 0, '7bc547068cfaea1d884f9819bc304dabb79872f9d5c254185753561d5b4222e0'),
    ('gwinnett_assessor', 315343, 2, 'e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca')
), runs AS (
    SELECT e.*, r.id, r.observed_on, r.metrics, r.artifact_sha256, r.raw_object_key
    FROM expected e LEFT JOIN provenance.source_dataset d ON d.dataset_key=e.dataset
    LEFT JOIN provenance.ingestion_run r ON r.dataset_id=d.id
), accepted AS (
    SELECT g.source_record_id AS id FROM core.parcel_geometry_version g
    UNION ALL
    SELECT s.source_record_id FROM core.ownership_record o JOIN evidence.claim_support s ON s.claim_id=o.claim_id
), output AS (
    SELECT id, count(*) AS publications FROM accepted GROUP BY id
), held AS (
    SELECT source_record_id AS id, count(*) AS holds FROM staging.review_item
    WHERE source_record_id IS NOT NULL GROUP BY source_record_id
), records AS MATERIALIZED (
    -- Keep only narrow fields across the position sort. Coverage is verified before
    -- comparing aggregates to run metrics, so metadata and locators are never sorted.
    SELECT r.id AS run, coalesce(o.publications,0) AS pubs, coalesce(h.holds,0) AS holds,
           CASE WHEN v.pos ~ '^[0-9]{1,8}$' THEN v.pos::integer END AS pos,
           (s.content_sha256 ~ '^[0-9a-f]{64}$' AND
            CASE WHEN r.dataset='gwinnett_parcels'
                THEN s.locator=jsonb_build_object('feature',s.locator->'feature') AND jsonb_typeof(s.locator->'feature')='number'
                ELSE s.locator=jsonb_build_object('workbook','tax_assessor_property_ownership_data/2026 Property Ownership.xlsx',
                         'sheet','Sheet1','row',s.locator->'row') AND jsonb_typeof(s.locator->'row')='number'
            END) IS TRUE AS valid_ref
    FROM runs r JOIN provenance.source_record s ON s.run_id=r.id
    CROSS JOIN LATERAL (VALUES(CASE WHEN r.dataset='gwinnett_parcels' THEN s.locator->>'feature' ELSE s.locator->>'row' END)) v(pos)
    LEFT JOIN output o ON o.id=s.id LEFT JOIN held h ON h.id=s.id
), totals AS (
    SELECT run, count(*) AS raw, sum(pubs) AS accepted, sum(holds) AS held,
           count(DISTINCT pos) AS positions, min(pos) AS first, max(pos) AS last,
           bool_and(valid_ref AND pubs+holds=1) AS refs_ok
    FROM records GROUP BY run
), quality AS (
    SELECT r.dataset, r.id, r.observed_on, t.raw, t.accepted, t.held,
           (r.artifact_sha256=r.sha AND r.raw_object_key=r.sha AND t.refs_ok AND t.raw=r.row_count
            AND t.raw=(r.metrics->>'read')::bigint AND t.accepted=(r.metrics->>'accepted')::bigint
            AND t.held=(r.metrics->>'quarantined')::bigint AND t.positions=r.row_count
            AND t.first=r.first_pos AND t.last=r.first_pos+r.row_count-1) IS TRUE AS ok
    FROM runs r LEFT JOIN totals t ON t.run=r.id
)
SELECT jsonb_agg(jsonb_build_object('dataset',dataset,'run',id,'observed_on',observed_on,'raw',raw,'accepted',accepted,'held',held,'passed',ok) ORDER BY dataset) AS summary,
       count(*)=2 AND count(id)=2 AND bool_and(ok AND accepted>0) AS ok
FROM quality
\gset runs_
\echo :runs_summary

-- Geometry rejection text may contain exact coordinates. Emit only fixed reason categories.
WITH reasons AS (
    SELECT d.dataset_key, CASE
        WHEN q.reason LIKE 'invalid parcel geometry:%' THEN 'invalid parcel geometry'
        WHEN q.reason IN ('missing PIN','negative deeded_acres','negative gis_acres','nonfinite acreage',
             'colliding source identifiers','missing polygon or unsupported geometry type','unsupported artifact CRS',
             'empty or non-2D parcel geometry','out-of-range WGS84 parcel geometry','invalid geometry encoding or coordinate transformation',
             'missing assessor PIN','ambiguous assessor PIN across workbook rows','ambiguous assessor LRSNum across workbook rows',
             'ambiguous GIS TAXPIN','unmatched assessor TAXPIN; LRSNum alone is insufficient','unmatched assessor TAXPIN',
             'assessor PIN and LRSNum identify different GIS parcels','ambiguous LRSN on matched GIS parcel',
             'assessor LRSNum differs from matched GIS parcel LRSN','missing assessor-listed owner') THEN q.reason
        ELSE 'other source review reason' END AS category, rr.id IS NULL AS unresolved
    FROM staging.review_item q JOIN provenance.source_record s ON s.id=q.source_record_id
    JOIN provenance.ingestion_run r ON r.id=s.run_id JOIN provenance.source_dataset d ON d.id=r.dataset_id
    LEFT JOIN staging.review_resolution rr ON rr.review_item_id=q.id
    WHERE d.dataset_key IN ('gwinnett_parcels','gwinnett_assessor')
)
SELECT dataset_key, category, count(*) AS held_rows, count(*) FILTER (WHERE unresolved) AS unresolved
FROM reasons GROUP BY dataset_key,category ORDER BY dataset_key,category;

-- Every private claim must have precisely one support. Compare its complete locator to the
-- original record and field. The literal table below is independent of the stored manifest.
WITH fields(dataset, predicate, source_field) AS (VALUES
    ('gwinnett_parcels','deeded_acres','DEEDEDACREAGE'), ('gwinnett_parcels','gis_acres','CALCULATEDACREAGE'),
    ('gwinnett_parcels','address','ADDRESS'), ('gwinnett_assessor','assessor_listed_owner','OWNERNAME1'),
    ('gwinnett_assessor','owner_line_2','OWNERNAME2'), ('gwinnett_assessor','mailing_street','OWNERADDRESS1'),
    ('gwinnett_assessor','mailing_city','OWNERCITY'), ('gwinnett_assessor','mailing_state','OWNERSTATE'),
    ('gwinnett_assessor','mailing_zip','OWNERZIP'), ('gwinnett_assessor','source_total_value','TOTVAL1'),
    ('gwinnett_assessor','source_tax_total','TAXTOT1')
), checked AS (
    SELECT count(*) FILTER (WHERE (f.source_field IS NOT NULL
           AND cs.locator = sr.locator || jsonb_build_object('field', f.source_field)
           AND c.subject_type='parcel' AND c.extraction_method='direct_mapping'
           AND c.observed_at=(r.observed_on::timestamp AT TIME ZONE 'UTC')) IS NOT TRUE) AS bad_locator_or_source
    FROM evidence.claim_support cs JOIN evidence.claim c ON cs.claim_id=c.id
    JOIN provenance.source_record sr ON sr.id=cs.source_record_id
    JOIN provenance.ingestion_run r ON r.id=sr.run_id JOIN provenance.source_dataset d ON d.id=r.dataset_id
    LEFT JOIN fields f ON f.dataset=d.dataset_key AND f.predicate=c.predicate
), multiplicities AS (
    -- The unique (claim_id, source_record_id) index can stream this narrow grouping.
    SELECT claim_id, count(*) AS supports FROM evidence.claim_support GROUP BY claim_id ORDER BY claim_id
), support_counts AS (
    SELECT count(*) AS represented, count(*) FILTER (WHERE supports>1) AS multiple FROM multiplicities
), all_claims AS (
    SELECT count(*) AS total FROM evidence.claim
)
SELECT total, total-represented+multiple AS wrong_support_count, bad_locator_or_source
FROM all_claims CROSS JOIN checked CROSS JOIN support_counts
\gset citation_
\echo claims=:citation_total wrong_support_count=:citation_wrong_support_count bad_field_or_source=:citation_bad_locator_or_source

-- Recover the TAXPIN join from the assessor source record. The workbook's secondary LRSNum
-- is in the retained artifact; its raw cross-check is documented in gwinnett_assessor_mapping.md.
WITH links AS (
    SELECT o.id, o.parcel_id, c.id AS claim_id, q.id AS held_id,
           (c.subject_type='parcel' AND c.subject_id=o.parcel_id AND c.predicate='assessor_listed_owner'
            AND o.ownership_kind=c.predicate AND o.observed_on=r.observed_on AND d.dataset_key='gwinnett_assessor'
            AND c.value->>'party_id'=o.party_id::text AND c.value->>'value'=party.canonical_name
            AND j.county_fips='13135' AND p.parcel_state='active' AND a.parcel_id=o.parcel_id) IS TRUE AS linked
    FROM core.ownership_record o LEFT JOIN evidence.claim c ON c.id=o.claim_id
    LEFT JOIN core.party party ON party.id=o.party_id LEFT JOIN core.parcel p ON p.id=o.parcel_id
    LEFT JOIN core.jurisdiction j ON j.id=p.jurisdiction_id LEFT JOIN evidence.claim_support cs ON cs.claim_id=c.id
    LEFT JOIN provenance.source_record sr ON sr.id=cs.source_record_id LEFT JOIN provenance.ingestion_run r ON r.id=sr.run_id
    LEFT JOIN provenance.source_dataset d ON d.id=r.dataset_id LEFT JOIN staging.review_item q ON q.source_record_id=sr.id
    LEFT JOIN core.parcel_identifier a ON a.dataset_id=(SELECT id FROM provenance.source_dataset WHERE dataset_key='gwinnett_parcels')
        AND a.identifier_type='taxpin' AND a.is_current AND a.normalized_value=upper(btrim(sr.external_record_id))
)
SELECT count(*) AS total, count(*) FILTER (WHERE NOT linked OR held_id IS NOT NULL) AS broken_or_held,
       count(*)-count(DISTINCT id) AS multiple_targets_or_supports,
       count(*)-count(DISTINCT parcel_id) AS repeated_parcels FROM links
\gset ownership_
\echo ownership=:ownership_total broken_or_held=:ownership_broken_or_held ambiguous_links=:ownership_multiple_targets_or_supports repeated_parcels=:ownership_repeated_parcels

-- Check every canonical geometry. Exercise interior-point coverage on every 997th source
-- position; the deterministic sample tests geometry selection only, not external accuracy.
SELECT count(*) AS total, count(*) FILTER (WHERE NOT (g.is_current AND ST_SRID(g.geom)=4326
           AND ST_GeometryType(g.geom)='ST_MultiPolygon' AND ST_NDims(g.geom)=2 AND NOT ST_IsEmpty(g.geom)
           AND ST_IsValid(g.geom,0) AND g.geom @ ST_MakeEnvelope(-84.5,33.5,-83.6,34.4,4326))) AS bad,
       count(*) FILTER (WHERE (s.locator->>'feature')::bigint % 997=0) AS sampled,
       count(*) FILTER (WHERE CASE WHEN (s.locator->>'feature')::bigint % 997=0 THEN NOT ST_Covers(g.geom,ST_PointOnSurface(g.geom)) ELSE false END) AS point_failures
FROM core.parcel_geometry_version g JOIN provenance.source_record s ON s.id=g.source_record_id
\gset geo_
\echo geometries=:geo_total invalid_or_outside_county_envelope=:geo_bad sample_size=:geo_sampled sample_failures=:geo_point_failures

SELECT :'policy_ok'::boolean AND :'runs_ok'::boolean AND :visible_source_records=0 AND :visible_parcels=0 AND :visible_claims=0
       AND :citation_total>0 AND :citation_wrong_support_count=0 AND :citation_bad_locator_or_source=0
       AND :ownership_total>0 AND :ownership_broken_or_held=0 AND :ownership_multiple_targets_or_supports=0 AND :ownership_repeated_parcels=0
       AND :geo_total>0 AND :geo_bad=0 AND :geo_sampled>0 AND :geo_point_failures=0 AS passed
\gset acceptance_
\if :acceptance_passed
    \echo PASS private Gwinnett baseline checks
\else
    DO $$ BEGIN RAISE EXCEPTION 'Private Gwinnett baseline checks failed'; END $$;
\endif

-- When the optional companion index is present, check original worksheet positions,
-- member hashes, ownership-source links, and the two reference dictionaries.
SELECT to_regclass('staging.gwinnett_companion_workbook') IS NOT NULL AS present
\gset companions_
\if :companions_present
WITH expected(filename, width, rows, linked, dictionary, sha) AS (VALUES
    ('CamaFull_Improv.xlsx', 82, 308830, 305803, false,
     '1546c4bf2ace94b41397f649c8a926f0d01b676489d5b4ea7f6f9f61ced38a6c'),
    ('CamaFull_Land.xlsx', 107, 323701, 315343, false,
     'de90c3ee941146aca6bf374e2d8859ae7ce822a1e13af74e02b21fba72fbb262'),
    ('Property Class Code List 2026.xlsx', 6, 284, 0, true,
     'ec55fbf351b6d47b8ae7d60c29a33c2945f8046814573c2685aabae72839a8a0'),
    ('TAX DIGEST OWNERSHIP LAYOUT.xlsx', 5, 42, 0, true,
     '96d7c718f713c8ce5778fcc98e224ff08f79f79aa2a275d84ec7a69feb890d19')
), counts AS (
    SELECT w.id,e.filename, count(r.excel_row) AS rows, count(r.ownership_source_record_id) AS linked,
           (count(r.excel_row)=e.rows AND min(r.excel_row)=2 AND max(r.excel_row)=e.rows+1
            AND count(r.ownership_source_record_id)=e.linked
            AND bool_and(w.reference_table=e.dictionary AND jsonb_array_length(w.headers)=e.width
                 AND w.member_sha256=e.sha AND w.sheet='Sheet1' AND d.dataset_key='gwinnett_assessor'
                 AND src.artifact_sha256='e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca'
                 AND (CASE WHEN e.dictionary THEN jsonb_array_length(r.reference_cells)=e.width
                           ELSE r.source_pin IS NOT NULL AND r.source_lrsn IS NOT NULL END) IS TRUE
                 AND (r.ownership_source_record_id IS NULL OR (s.run_id=w.run_id AND
                      s.external_record_id=r.source_pin AND s.locator->>'sheet'='Sheet1' AND
                      s.locator->>'workbook'='tax_assessor_property_ownership_data/2026 Property Ownership.xlsx') IS TRUE))) AS ok
    FROM expected e LEFT JOIN staging.gwinnett_companion_workbook w
      ON w.workbook='tax_assessor_property_ownership_data/'||e.filename
    LEFT JOIN provenance.ingestion_run src ON src.id=w.run_id
    LEFT JOIN provenance.source_dataset d ON d.id=src.dataset_id
    LEFT JOIN staging.gwinnett_companion_row r ON r.workbook_id=w.id
    LEFT JOIN provenance.source_record s ON s.id=r.ownership_source_record_id
    GROUP BY w.id,e.filename,e.rows,e.linked
)
SELECT sum(rows) AS rows, sum(linked) AS linked, count(id)=4 AND bool_and(ok IS TRUE)
    AND (SELECT count(*) FROM staging.gwinnett_companion_workbook)=4 AS ok FROM counts
\gset companions_
\echo companion_worksheet_rows=:companions_rows linked_to_ownership_source_rows=:companions_linked
\if :companions_ok
    \echo PASS private companion index checks
\else
    DO $$ BEGIN RAISE EXCEPTION 'Private companion index checks failed'; END $$;
\endif
\endif

-- Every accepted ownership row in this release has a populated site street.
-- Compare both parcel and source-record IDs so a link to a different parcel fails.
\if :{?require_situs}
\else
    \set require_situs false
\endif
SELECT to_regclass('staging.gwinnett_situs_address') IS NOT NULL AS present
\gset situs_
\if :situs_present
WITH owners AS (
    SELECT o.parcel_id, cs.source_record_id
    FROM core.ownership_record o
    JOIN evidence.claim_support cs ON cs.claim_id=o.claim_id
), compared AS (
    SELECT a.source_record_id IS NOT NULL AS indexed,
           o.source_record_id IS NULL OR a.source_record_id IS NULL AS broken_link,
           (a.source_field='PROPERTYSTREET' AND btrim(a.raw_address)<>''
            AND s.locator->>'workbook'='tax_assessor_property_ownership_data/2026 Property Ownership.xlsx'
            AND s.locator->>'sheet'='Sheet1' AND jsonb_typeof(s.locator->'row')='number'
            AND d.dataset_key='gwinnett_assessor') IS TRUE AS cited
    FROM staging.gwinnett_situs_address a FULL JOIN owners o USING (parcel_id,source_record_id)
    LEFT JOIN provenance.source_record s ON s.id=a.source_record_id
    LEFT JOIN provenance.ingestion_run r ON r.id=s.run_id
    LEFT JOIN provenance.source_dataset d ON d.id=r.dataset_id
)
SELECT count(*) FILTER (WHERE indexed) AS indexed, count(*) FILTER (WHERE broken_link OR NOT cited) AS invalid,
       count(*)=:ownership_total AND bool_and(NOT broken_link AND cited) AS ok
FROM compared
\gset situs_
\echo private_site_addresses=:situs_indexed missing_or_incorrect_citations=:situs_invalid
\if :situs_ok
    \echo PASS private assessor site-address checks
\else
    DO $$ BEGIN RAISE EXCEPTION 'Private assessor site-address checks failed'; END $$;
\endif
\elif :require_situs
    DO $$ BEGIN RAISE EXCEPTION 'Missing private assessor site-address index'; END $$;
\else
    \echo SKIP private assessor site-address checks: index is absent
\endif

COMMIT;
