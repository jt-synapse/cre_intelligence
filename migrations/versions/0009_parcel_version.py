"""Pin parcel geometry and permitted evidence to an atomic county reader generation."""

from alembic import op

revision = "0009_parcel_version"
down_revision = "0008_snapshot_dates"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE core.reader_generation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), county_fips text NOT NULL,
        run_ids uuid[] NOT NULL, active boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
    op.execute(
        "CREATE UNIQUE INDEX reader_current ON core.reader_generation(county_fips) WHERE active"
    )
    op.execute("""CREATE TABLE core.reader_parcel (
        generation_id uuid NOT NULL REFERENCES core.reader_generation,
        parcel_id uuid NOT NULL REFERENCES core.parcel,
        geometry_version_id uuid NOT NULL REFERENCES core.parcel_geometry_version,
        PRIMARY KEY(generation_id,parcel_id))""")
    op.execute("""CREATE TABLE core.reader_claim_support (
        generation_id uuid NOT NULL REFERENCES core.reader_generation,
        claim_id uuid NOT NULL REFERENCES evidence.claim,
        source_record_id uuid NOT NULL REFERENCES provenance.source_record,
        PRIMARY KEY(generation_id,claim_id,source_record_id))""")
    op.execute("""CREATE FUNCTION core.advance_parcel_reader(candidate uuid, recovered boolean DEFAULT false) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE item record; partners text[]; bundle uuid[]; previous core.reader_generation;
            new_generation uuid; chosen uuid[]; county text;
    BEGIN
      SELECT r.*,d.dataset_key INTO STRICT item FROM provenance.ingestion_run r
        JOIN provenance.source_dataset d ON d.id=r.dataset_id WHERE r.id=candidate;
      county := item.manifest->>'county_fips';
      PERFORM pg_advisory_xact_lock(174274,county::integer);
      SELECT ARRAY(SELECT DISTINCT name FROM (
        SELECT item.dataset_key AS name UNION ALL SELECT jsonb_array_elements_text(
        COALESCE(item.manifest->'paired_datasets','[]'::jsonb))) names ORDER BY name) INTO partners;
      SELECT array_agg(ready.id) INTO bundle FROM (
        SELECT DISTINCT ON (d.dataset_key) r.id FROM provenance.ingestion_run r
        JOIN provenance.source_dataset d ON d.id=r.dataset_id
        WHERE d.enabled AND d.shared_display AND d.dataset_key=ANY(partners)
          AND r.manifest->>'county_fips'=county AND r.observed_on=item.observed_on
          AND (r.manifest->>'reader_release') IS NOT DISTINCT FROM (item.manifest->>'reader_release')
          AND (r.metrics->>'accepted')::integer>0
          AND (r.metrics->>'read')::integer=(r.metrics->>'accepted')::integer+(r.metrics->>'quarantined')::integer
          AND (r.manifest->>'expected_snapshot_rows' IS NULL OR
              (r.metrics->>'read')::integer=(r.manifest->>'expected_snapshot_rows')::integer)
          AND ARRAY(SELECT DISTINCT k FROM (
              SELECT d.dataset_key k UNION ALL SELECT jsonb_array_elements_text(
              COALESCE(r.manifest->'paired_datasets','[]'::jsonb))) keys ORDER BY k)=partners
        ORDER BY d.dataset_key,r.published_at DESC,r.id DESC) ready;
      IF cardinality(bundle) IS DISTINCT FROM cardinality(partners) OR NOT candidate=ANY(bundle) THEN RETURN; END IF;
      SELECT * INTO previous FROM core.reader_generation WHERE county_fips=county AND active;
      IF bundle <@ previous.run_ids AND NOT recovered THEN RETURN; END IF;
      IF EXISTS(SELECT 1 FROM provenance.ingestion_run old JOIN provenance.ingestion_run new
        ON old.dataset_id=new.dataset_id WHERE old.id=ANY(previous.run_ids) AND new.id=ANY(bundle)
        AND (old.observed_on,old.published_at)>(new.observed_on,new.published_at)) THEN RETURN; END IF;
      -- A complete input replaces its dataset. Incremental inputs carry earlier members forward.
      SELECT ARRAY(SELECT DISTINCT r.id FROM provenance.ingestion_run r WHERE r.id=ANY(bundle)
        OR (r.id=ANY(previous.run_ids) AND NOT EXISTS (SELECT 1 FROM provenance.ingestion_run n
        WHERE n.id=ANY(bundle) AND n.dataset_id=r.dataset_id AND n.manifest->>'expected_snapshot_rows' IS NOT NULL))
        ORDER BY r.id) INTO chosen;
      INSERT INTO core.reader_generation(county_fips,run_ids) VALUES(county,chosen) RETURNING id INTO new_generation;
      INSERT INTO core.reader_parcel
        SELECT DISTINCT ON (g.parcel_id) new_generation,g.parcel_id,g.id
        FROM core.parcel_geometry_version g JOIN provenance.source_record s ON s.id=g.source_record_id
        JOIN provenance.ingestion_run r ON r.id=s.run_id WHERE r.id=ANY(chosen)
        ORDER BY g.parcel_id,g.observed_at DESC,r.published_at DESC,g.id DESC;
      INSERT INTO core.reader_claim_support
        SELECT new_generation,c.id,cs.source_record_id FROM core.reader_parcel m
        JOIN evidence.claim c ON c.subject_type='parcel' AND c.subject_id=m.parcel_id
        JOIN evidence.claim_support cs ON cs.claim_id=c.id
        JOIN provenance.source_record sr ON sr.id=cs.source_record_id
        WHERE m.generation_id=new_generation AND sr.run_id=ANY(chosen);
      UPDATE core.reader_generation SET active=false WHERE id=previous.id;
      UPDATE core.reader_generation SET active=true WHERE id=new_generation;
    END $$""")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION core.advance_parcel_reader(uuid,boolean) FROM PUBLIC"
    )
    op.execute("""DO $$ DECLARE rec record; BEGIN
        FOR rec IN SELECT r.id FROM provenance.ingestion_run r JOIN provenance.source_dataset d
        ON d.id=r.dataset_id WHERE d.enabled AND d.shared_display ORDER BY r.observed_on,r.published_at
        LOOP PERFORM core.advance_parcel_reader(rec.id); END LOOP; END $$""")
    op.execute("""CREATE OR REPLACE VIEW core.visible_parcel WITH(security_barrier=true) AS
        SELECT p.id,p.jurisdiction_id,j.county_fips,g.primary_pin,g.normalized_pin,g.address,g.geom,
          g.observed_at,g.source_record_id,s.dataset_key,s.export_allowed,s.publisher,s.source_origin,
          s.attribution,s.content_sha256,s.run_id,g.id AS geometry_version_id,
          h.id AS projection_generation_id,h.id::text AS reader_version
        FROM core.reader_generation h JOIN core.reader_parcel m ON m.generation_id=h.id
        JOIN core.parcel_geometry_version g ON g.id=m.geometry_version_id
        JOIN core.parcel p ON p.id=m.parcel_id JOIN core.jurisdiction j ON j.id=p.jurisdiction_id
        JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id
        WHERE h.active AND p.parcel_state='active'""")
    op.execute("""CREATE VIEW evidence.reader_parcel_claim WITH(security_barrier=true) AS
        WITH pinned AS (
          SELECT c.id,c.subject_id,c.subject_type,c.predicate,c.value,c.verification_state AS recorded_state,
            c.observed_at,s.source_record_id,cs.locator,s.dataset_key,s.export_allowed,s.publisher,s.source_origin,
            s.attribution,s.content_sha256,s.run_id,h.id AS projection_generation_id
          FROM core.reader_generation h JOIN core.reader_claim_support m ON m.generation_id=h.id
          JOIN evidence.claim c ON c.id=m.claim_id JOIN evidence.claim_support cs
            ON cs.claim_id=c.id AND cs.source_record_id=m.source_record_id
          JOIN provenance.visible_source_record s ON s.source_record_id=cs.source_record_id
          JOIN core.visible_parcel v ON v.id=c.subject_id AND v.projection_generation_id=h.id
          WHERE h.active)
        SELECT p.*,coalesce((SELECT review.decision FROM evidence.claim_review_event review
          WHERE review.claim_id=p.id AND review.decision IN
            ('verified','corroborated','conflicted','stale','unresolved','candidate')
          ORDER BY review.created_at DESC,review.id DESC LIMIT 1),
          CASE WHEN p.predicate='assessor_listed_owner' AND EXISTS(
            SELECT 1 FROM core.reader_claim_support m JOIN evidence.claim other ON other.id=m.claim_id
            JOIN provenance.visible_source_record sr ON sr.source_record_id=m.source_record_id
            WHERE m.generation_id=p.projection_generation_id AND other.subject_id=p.subject_id
            AND other.predicate=p.predicate AND other.observed_at=p.observed_at
            AND upper(trim(other.value->>'value'))<>upper(trim(p.value->>'value')))
          THEN 'conflicted' ELSE p.recorded_state END) AS verification_state FROM pinned p""")
    op.execute("""CREATE VIEW evidence.reader_owner WITH(security_barrier=true) AS
        SELECT ranked.* FROM (SELECT c.*,dense_rank() OVER (
        PARTITION BY c.subject_id,c.dataset_key ORDER BY c.observed_at DESC) AS recency
        FROM evidence.reader_parcel_claim c WHERE c.predicate='assessor_listed_owner') ranked WHERE recency=1""")
    op.execute("""CREATE VIEW evidence.reader_control WITH(security_barrier=true) AS
        SELECT rel.subject_party_id AS controller,rel.object_party_id AS controlled,
            c.source_record_id,c.dataset_key,c.observed_at
        FROM core.party_relationship rel JOIN evidence.visible_claim c ON c.id=rel.claim_id
        WHERE rel.relationship_type='controls' AND c.verification_state IN ('corroborated','verified')
        AND c.predicate='controls' AND c.subject_id=rel.subject_party_id
        AND c.value->>'party_id'=rel.object_party_id::text""")


def downgrade():
    # Keep additive version columns for existing consumers of the entitlement view.
    op.execute(
        "DROP VIEW evidence.reader_control, evidence.reader_owner, evidence.reader_parcel_claim"
    )
    op.execute("""CREATE OR REPLACE VIEW core.visible_parcel WITH(security_barrier=true) AS
        SELECT p.id,p.jurisdiction_id,j.county_fips,g.primary_pin,g.normalized_pin,g.address,g.geom,
        g.observed_at,g.source_record_id,s.dataset_key,s.export_allowed,s.publisher,s.source_origin,
        s.attribution,s.content_sha256,s.run_id,g.id AS geometry_version_id,
        NULL::uuid AS projection_generation_id,NULL::text AS reader_version FROM core.parcel p
        JOIN core.jurisdiction j ON j.id=p.jurisdiction_id JOIN core.parcel_geometry_version g
        ON g.parcel_id=p.id AND g.is_current JOIN provenance.visible_source_record s
        ON s.source_record_id=g.source_record_id WHERE p.parcel_state='active'""")
    op.execute("DROP FUNCTION core.advance_parcel_reader(uuid,boolean)")
    op.execute(
        "DROP TABLE core.reader_claim_support,core.reader_parcel,core.reader_generation"
    )
