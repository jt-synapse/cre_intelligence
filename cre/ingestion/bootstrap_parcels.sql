-- The caller owns the transaction, the county publication lock, and the retained raw
-- artifact. This path creates the first set of parcels in a private county namespace.
DO $$
BEGIN
    IF (SELECT count(*) FROM pg_temp.batch) <> 1 OR NOT EXISTS (
        SELECT FROM pg_temp.batch b
        JOIN provenance.ingestion_run r ON r.id = b.run_id AND r.dataset_id = b.dataset_id
        JOIN provenance.ingestion_attempt a ON a.id = b.attempt_id AND a.dataset_id = b.dataset_id
        JOIN provenance.source_dataset d ON d.id = b.dataset_id
        JOIN core.jurisdiction j ON j.id = b.jurisdiction_id
        WHERE r.observed_on = b.observed AND a.observed_on = b.observed
          AND d.enabled AND NOT d.shared_display AND NOT d.export_allowed
          AND d.manifest->>'kind' = 'parcels'
          AND d.manifest->>'county_fips' = j.county_fips
    ) THEN
        RAISE EXCEPTION 'expected one private parcel publication with matching provenance';
    END IF;
    IF EXISTS (SELECT FROM core.parcel p JOIN pg_temp.batch b ON p.jurisdiction_id = b.jurisdiction_id)
       OR EXISTS (SELECT FROM provenance.ingestion_run r JOIN pg_temp.batch b
                  ON r.dataset_id = b.dataset_id AND r.id <> b.run_id
                  WHERE (r.metrics->>'accepted')::bigint IS DISTINCT FROM 0)
       OR EXISTS (SELECT FROM provenance.source_record s JOIN pg_temp.batch b ON s.run_id = b.run_id)
    THEN
        RAISE EXCEPTION 'parcel bootstrap requires an empty county and a new run';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_temp.incoming_parcel) THEN
        RAISE EXCEPTION 'empty parcel snapshot requires review';
    END IF;
END $$;

ANALYZE pg_temp.batch;
ANALYZE pg_temp.incoming_parcel;

CREATE OR REPLACE FUNCTION pg_temp.bootstrap_shape(payload text, source_srid integer,
    OUT geom geometry, OUT problem text)
LANGUAGE plpgsql AS $$
BEGIN
    IF payload IS NULL THEN
        problem := 'missing polygon or unsupported geometry type';
        RETURN;
    END IF;
    IF source_srid IS NULL OR source_srid NOT IN (2240, 4326) THEN
        problem := 'unsupported artifact CRS';
        RETURN;
    END IF;
    geom := ST_SetSRID(ST_GeomFromGeoJSON(payload), source_srid);
    IF geom IS NULL OR ST_GeometryType(geom) NOT IN ('ST_Polygon', 'ST_MultiPolygon') THEN
        problem := 'missing polygon or unsupported geometry type';
    ELSIF ST_NDims(geom) <> 2 OR ST_IsEmpty(geom) THEN
        problem := 'empty or non-2D parcel geometry';
    ELSE
        IF source_srid <> 4326 THEN
            geom := ST_Transform(geom, 4326);
        END IF;
        IF NOT ST_IsValid(geom, 0) THEN
            problem := 'invalid parcel geometry: ' || ST_IsValidReason(geom);
        ELSIF NOT (ST_XMin(geom) >= -180 AND ST_XMax(geom) <= 180
                   AND ST_YMin(geom) >= -90 AND ST_YMax(geom) <= 90) THEN
            problem := 'out-of-range WGS84 parcel geometry';
        ELSE
            geom := ST_Multi(geom);
        END IF;
    END IF;
    IF problem IS NOT NULL THEN
        geom := NULL;
    END IF;
EXCEPTION WHEN data_exception OR SQLSTATE 'XX000' THEN
    geom := NULL;
    problem := 'invalid geometry encoding or coordinate transformation';
END $$;

INSERT INTO provenance.source_record(id, run_id, external_record_id, content_sha256, locator)
SELECT i.record_id, b.run_id, i.ext_id, i.digest, i.loc
FROM pg_temp.incoming_parcel i CROSS JOIN pg_temp.batch b;

-- The source PIN is authoritative within the county. Other aliases are scoped
-- by dataset and type, as in the incremental parcel publisher.
CREATE TEMP TABLE bootstrap_alias ON COMMIT DROP AS
SELECT i.record_id, a.kind, a.raw, a.normalized
FROM pg_temp.incoming_parcel i
CROSS JOIN LATERAL (VALUES
    ('pin', i.pin, regexp_replace(upper(i.pin), '[-[:space:]]+', '', 'g')),
    ('taxpin', i.taxpin, upper(regexp_replace(i.taxpin, '^[[:space:]]+|[[:space:]]+$', '', 'g'))),
    ('lrsn', i.lrsn, upper(regexp_replace(i.lrsn, '^[[:space:]]+|[[:space:]]+$', '', 'g'))),
    ('global_id', i.gid, upper(regexp_replace(i.gid, '^[[:space:]]+|[[:space:]]+$', '', 'g')))
) AS a(kind, raw, normalized)
WHERE a.normalized <> '';
ANALYZE pg_temp.bootstrap_alias;

CREATE TEMP TABLE bootstrap_collision ON COMMIT DROP AS
SELECT DISTINCT a.record_id
FROM pg_temp.bootstrap_alias a
JOIN (
    SELECT kind, normalized FROM pg_temp.bootstrap_alias
    GROUP BY kind, normalized HAVING count(*) > 1
) repeated USING (kind, normalized);
ANALYZE pg_temp.bootstrap_collision;

CREATE TEMP TABLE bootstrap_parcel ON COMMIT DROP AS
WITH screened AS (
    SELECT i.*, p.normalized AS normalized_pin,
           COALESCE(i.reason, CASE
               WHEN p.normalized IS NULL THEN 'missing PIN'
               WHEN i.deeded < 0 THEN 'negative deeded_acres'
               WHEN i.acres < 0 THEN 'negative gis_acres'
               WHEN i.deeded::text IN ('NaN', 'Infinity', '-Infinity')
                 OR i.acres::text IN ('NaN', 'Infinity', '-Infinity') THEN 'nonfinite acreage'
               WHEN c.record_id IS NOT NULL THEN 'colliding source identifiers'
           END) AS issue
    FROM pg_temp.incoming_parcel i
    LEFT JOIN pg_temp.bootstrap_alias p ON p.kind = 'pin' AND p.record_id = i.record_id
    LEFT JOIN pg_temp.bootstrap_collision c ON c.record_id = i.record_id
)
SELECT s.record_id, gen_random_uuid() AS parcel_id, s.loc, s.pin, s.normalized_pin,
       s.address, s.deeded, s.acres, g.geom, COALESCE(s.issue, g.problem) AS reason
FROM screened s
CROSS JOIN LATERAL pg_temp.bootstrap_shape(
    CASE WHEN s.issue IS NULL THEN s.geometry_json END, s.srid
) g;
ANALYZE pg_temp.bootstrap_parcel;

INSERT INTO staging.review_item(attempt_id, source_record_id, reason, locator)
SELECT b.attempt_id, p.record_id, p.reason, p.loc
FROM pg_temp.bootstrap_parcel p CROSS JOIN pg_temp.batch b
WHERE p.reason IS NOT NULL;

INSERT INTO core.parcel(id, jurisdiction_id, primary_pin, normalized_pin)
SELECT p.parcel_id, b.jurisdiction_id, p.pin, p.normalized_pin
FROM pg_temp.bootstrap_parcel p CROSS JOIN pg_temp.batch b
WHERE p.reason IS NULL;

INSERT INTO core.parcel_identifier(parcel_id, dataset_id, identifier_type, identifier_value,
                                   normalized_value, source_record_id, first_seen, last_seen)
SELECT p.parcel_id, b.dataset_id, a.kind, a.raw, a.normalized, p.record_id, b.observed, b.observed
FROM pg_temp.bootstrap_alias a JOIN pg_temp.bootstrap_parcel p USING (record_id)
CROSS JOIN pg_temp.batch b
WHERE p.reason IS NULL;

INSERT INTO core.parcel_geometry_version(parcel_id, source_record_id, geom, observed_at,
                                         is_current, primary_pin, normalized_pin, address)
SELECT p.parcel_id, p.record_id, p.geom, b.observed::timestamp AT TIME ZONE 'UTC',
       true, p.pin, p.normalized_pin, p.address
FROM pg_temp.bootstrap_parcel p CROSS JOIN pg_temp.batch b
WHERE p.reason IS NULL;

INSERT INTO core.address(parcel_id, source_record_id, raw_address, normalized_address)
SELECT p.parcel_id, p.record_id, p.address, trim(regexp_replace(upper(p.address), '[[:space:]]+', ' ', 'g'))
FROM pg_temp.bootstrap_parcel p
WHERE p.reason IS NULL AND p.address ~ '[^[:space:]]';

-- Assign claim IDs once so each field citation points at exactly its own claim.
CREATE TEMP TABLE bootstrap_claim ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, p.parcel_id, p.record_id, f.kind, f.value,
       p.loc || jsonb_build_object('field', b.columns->>f.kind) AS locator
FROM pg_temp.bootstrap_parcel p CROSS JOIN pg_temp.batch b
CROSS JOIN LATERAL (VALUES
    ('deeded_acres', to_jsonb(p.deeded)), ('gis_acres', to_jsonb(p.acres)), ('address', to_jsonb(p.address))
) AS f(kind, value)
WHERE p.reason IS NULL AND f.value IS NOT NULL AND b.columns ? f.kind;

INSERT INTO evidence.claim(id, subject_type, subject_id, predicate, value, verification_state,
                           observed_at, extraction_method)
SELECT c.id, 'parcel', c.parcel_id, c.kind, jsonb_build_object('value', c.value),
       'verified', b.observed::timestamp AT TIME ZONE 'UTC', 'direct_mapping'
FROM pg_temp.bootstrap_claim c CROSS JOIN pg_temp.batch b;

INSERT INTO evidence.claim_support(claim_id, source_record_id, locator)
SELECT id, record_id, locator FROM pg_temp.bootstrap_claim;

CREATE TEMP TABLE batch_counts ON COMMIT DROP AS
SELECT count(*) AS read, count(*) FILTER (WHERE reason IS NULL) AS accepted,
       count(reason) AS quarantined, 0::bigint AS unmatched,
       count(*) FILTER (WHERE reason = 'colliding source identifiers') AS conflicting
FROM pg_temp.bootstrap_parcel;
