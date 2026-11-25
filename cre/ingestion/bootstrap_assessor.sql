-- The inspected assessor PIN is the parcel publisher's TAXPIN. LRSNum can
-- disprove this match, but cannot establish a parcel match by itself.
CREATE TEMP TABLE bootstrap_gis_source ON COMMIT DROP AS
SELECT g.id
FROM pg_temp.batch b
JOIN provenance.ingestion_run r ON r.id = b.run_id AND r.dataset_id = b.dataset_id
JOIN provenance.ingestion_attempt a ON a.id = b.attempt_id AND a.dataset_id = b.dataset_id
JOIN provenance.source_dataset d ON d.id = b.dataset_id
JOIN core.jurisdiction j ON j.id = b.jurisdiction_id
JOIN provenance.source_dataset g ON g.dataset_key = d.manifest->>'join_dataset'
WHERE r.observed_on = b.observed AND a.observed_on = b.observed
  AND d.enabled AND NOT d.shared_display AND NOT d.export_allowed
  AND g.enabled AND NOT g.shared_display AND NOT g.export_allowed
  AND d.manifest->>'kind' = 'assessor' AND g.manifest->>'kind' = 'parcels'
  AND d.manifest->>'county_fips' = j.county_fips AND g.manifest->>'county_fips' = j.county_fips
  AND d.manifest->>'join_identifier' = 'taxpin' AND b.columns->>'owner' = 'OWNERNAME1';

DO $$
BEGIN
    IF (SELECT count(*) FROM pg_temp.batch) <> 1
       OR (SELECT count(*) FROM pg_temp.bootstrap_gis_source) <> 1 THEN
        RAISE EXCEPTION 'expected a private assessor publication with its reviewed GIS TAXPIN namespace';
    END IF;
    IF EXISTS (SELECT FROM provenance.ingestion_run r JOIN pg_temp.batch b
               ON r.dataset_id = b.dataset_id AND r.id <> b.run_id
               WHERE (r.metrics->>'accepted')::bigint IS DISTINCT FROM 0)
       OR EXISTS (SELECT FROM provenance.source_record s JOIN pg_temp.batch b ON s.run_id = b.run_id)
       OR EXISTS (SELECT FROM core.ownership_record o JOIN core.parcel p ON p.id = o.parcel_id
                  JOIN pg_temp.batch b ON b.jurisdiction_id = p.jurisdiction_id) THEN
        RAISE EXCEPTION 'assessor bootstrap requires a new run and no existing county ownership';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_temp.incoming_assessor) THEN
        RAISE EXCEPTION 'empty assessor snapshot requires review';
    END IF;
END $$;

ANALYZE pg_temp.batch;
ANALYZE pg_temp.bootstrap_gis_source;
ANALYZE pg_temp.incoming_assessor;

INSERT INTO provenance.source_record(id, run_id, external_record_id, content_sha256, locator)
SELECT i.record_id, b.run_id, i.ext_id, i.digest, i.loc
FROM pg_temp.incoming_assessor i CROSS JOIN pg_temp.batch b;

CREATE TEMP TABLE bootstrap_gis_alias ON COMMIT DROP AS
SELECT i.parcel_id, i.identifier_type, i.normalized_value AS normalized
FROM core.parcel_identifier i JOIN pg_temp.bootstrap_gis_source gs ON gs.id = i.dataset_id
JOIN core.parcel p ON p.id = i.parcel_id JOIN pg_temp.batch b ON b.jurisdiction_id = p.jurisdiction_id
WHERE i.is_current AND p.parcel_state = 'active' AND i.identifier_type IN ('taxpin', 'lrsn');
ANALYZE pg_temp.bootstrap_gis_alias;

CREATE TEMP TABLE bootstrap_taxpin ON COMMIT DROP AS
SELECT normalized, (array_agg(parcel_id))[1] AS parcel_id, count(DISTINCT parcel_id) AS targets
FROM pg_temp.bootstrap_gis_alias WHERE identifier_type = 'taxpin' AND normalized <> ''
GROUP BY normalized;
ANALYZE pg_temp.bootstrap_taxpin;

CREATE TEMP TABLE bootstrap_gis_lrsn ON COMMIT DROP AS
SELECT parcel_id, min(normalized) AS normalized, count(*) AS aliases
FROM pg_temp.bootstrap_gis_alias WHERE identifier_type = 'lrsn' GROUP BY parcel_id;
ANALYZE pg_temp.bootstrap_gis_lrsn;

CREATE TEMP TABLE bootstrap_assessment ON COMMIT DROP AS
WITH normalized AS (
    SELECT i.*, nullif(upper(regexp_replace(i.pin, '^[[:space:]]+|[[:space:]]+$', '', 'g')), '') AS tax_key,
           nullif(trim(i.lrsn), '') AS lrs_key
    FROM pg_temp.incoming_assessor i
), counted AS (
    SELECT n.*, count(*) OVER (PARTITION BY tax_key) AS pin_rows,
           count(*) OVER (PARTITION BY lrs_key) AS lrsn_rows
    FROM normalized n
)
SELECT i.record_id, i.loc, i.owner, i.details, t.parcel_id,
       gen_random_uuid() AS party_id, gen_random_uuid() AS owner_claim_id,
       coalesce(i.reason, CASE
           WHEN i.tax_key IS NULL THEN 'missing assessor PIN'
           WHEN i.pin_rows > 1 THEN 'ambiguous assessor PIN across workbook rows'
           WHEN i.lrs_key IS NOT NULL AND i.lrsn_rows > 1 THEN 'ambiguous assessor LRSNum across workbook rows'
           WHEN t.targets > 1 THEN 'ambiguous GIS TAXPIN'
           WHEN t.parcel_id IS NULL AND alt.parcel_id IS NOT NULL THEN 'unmatched assessor TAXPIN; LRSNum alone is insufficient'
           WHEN t.parcel_id IS NULL THEN 'unmatched assessor TAXPIN'
           WHEN alt.parcel_id <> t.parcel_id THEN 'assessor PIN and LRSNum identify different GIS parcels'
           WHEN i.lrs_key IS NOT NULL AND target_lrsn.aliases > 1 THEN 'ambiguous LRSN on matched GIS parcel'
           WHEN target_lrsn.normalized <> i.lrs_key THEN 'assessor LRSNum differs from matched GIS parcel LRSN'
           WHEN i.owner IS NULL OR i.owner !~ '[^[:space:]]' THEN 'missing assessor-listed owner'
       END) AS reason
FROM counted i
LEFT JOIN pg_temp.bootstrap_taxpin t ON t.normalized = i.tax_key
LEFT JOIN pg_temp.bootstrap_gis_lrsn target_lrsn ON target_lrsn.parcel_id = t.parcel_id
LEFT JOIN pg_temp.bootstrap_gis_alias alt ON alt.identifier_type = 'lrsn' AND alt.normalized = i.lrs_key;
ANALYZE pg_temp.bootstrap_assessment;

INSERT INTO staging.review_item(attempt_id, source_record_id, reason, locator)
SELECT b.attempt_id, s.record_id, s.reason, s.loc
FROM pg_temp.bootstrap_assessment s CROSS JOIN pg_temp.batch b WHERE s.reason IS NOT NULL;

-- A matching name on another parcel is insufficient evidence of party identity.
INSERT INTO core.party(id, party_type, canonical_name)
SELECT s.party_id, CASE WHEN s.owner ~* '\m(LLC|INC|CORP|LP|LTD)\.?$'
                        THEN 'organization' ELSE 'unknown' END, s.owner
FROM pg_temp.bootstrap_assessment s WHERE s.reason IS NULL;

CREATE TEMP TABLE bootstrap_owner_claim ON COMMIT DROP AS
SELECT s.owner_claim_id AS id, s.parcel_id, s.record_id, 'assessor_listed_owner'::text AS predicate,
       jsonb_build_object('value', s.owner, 'party_id', s.party_id) AS value,
       s.loc || jsonb_build_object('field', b.columns->>'owner') AS locator
FROM pg_temp.bootstrap_assessment s CROSS JOIN pg_temp.batch b WHERE s.reason IS NULL
UNION ALL
SELECT gen_random_uuid(), s.parcel_id, s.record_id, f.key, jsonb_build_object('value', f.value),
       s.loc || jsonb_build_object('field', b.columns->>f.key)
FROM pg_temp.bootstrap_assessment s CROSS JOIN pg_temp.batch b
CROSS JOIN LATERAL jsonb_each(s.details) f
WHERE s.reason IS NULL AND b.columns ? f.key AND f.value <> 'null'::jsonb
  AND (jsonb_typeof(f.value) <> 'string' OR (f.value #>> '{}') ~ '[^[:space:]]')
  AND f.key IN ('owner_line_2', 'mailing_street', 'mailing_city', 'mailing_state', 'mailing_zip',
                'source_total_value', 'source_tax_total');

INSERT INTO evidence.claim(id, subject_type, subject_id, predicate, value, verification_state,
                           observed_at, extraction_method)
SELECT c.id, 'parcel', c.parcel_id, c.predicate, c.value, 'verified',
       b.observed::timestamp AT TIME ZONE 'UTC', 'direct_mapping'
FROM pg_temp.bootstrap_owner_claim c CROSS JOIN pg_temp.batch b;

INSERT INTO evidence.claim_support(claim_id, source_record_id, locator)
SELECT id, record_id, locator FROM pg_temp.bootstrap_owner_claim;

INSERT INTO core.ownership_record(parcel_id, party_id, ownership_kind, claim_id, observed_on)
SELECT s.parcel_id, s.party_id, 'assessor_listed_owner', s.owner_claim_id, b.observed
FROM pg_temp.bootstrap_assessment s CROSS JOIN pg_temp.batch b WHERE s.reason IS NULL;

CREATE TEMP TABLE batch_counts ON COMMIT DROP AS
SELECT count(*) AS read, count(*) FILTER (WHERE reason IS NULL) AS accepted,
       count(reason) AS quarantined,
       count(*) FILTER (WHERE reason LIKE 'unmatched assessor TAXPIN%') AS unmatched,
       count(*) FILTER (WHERE reason IN ('ambiguous assessor PIN across workbook rows',
           'ambiguous assessor LRSNum across workbook rows', 'ambiguous GIS TAXPIN',
           'assessor PIN and LRSNum identify different GIS parcels', 'ambiguous LRSN on matched GIS parcel',
           'assessor LRSNum differs from matched GIS parcel LRSN')) AS conflicting
FROM pg_temp.bootstrap_assessment;
