"""Canonical parcel, evidence, and source publication contracts."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Separate statements are portable across psycopg execution modes.
    for extension in ("postgis", "btree_gist"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    for schema in ("provenance", "core", "evidence", "staging", "operations"):
        op.execute(f"CREATE SCHEMA {schema}")
    for statement in DDL:
        op.execute(statement)


def downgrade():
    for schema in ("operations", "staging", "evidence", "core", "provenance"):
        op.execute(f"DROP SCHEMA {schema} CASCADE")


DDL = [
    """CREATE TABLE provenance.source_system (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_key text NOT NULL UNIQUE, publisher text NOT NULL)""",
    """CREATE TABLE provenance.source_dataset (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_system_id uuid NOT NULL REFERENCES provenance.source_system,
        dataset_key text NOT NULL UNIQUE, manifest jsonb NOT NULL,
        enabled boolean NOT NULL, shared_display boolean NOT NULL, export_allowed boolean NOT NULL)""",
    """CREATE TABLE provenance.manifest_event (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES provenance.source_dataset,
        observed_at timestamptz NOT NULL DEFAULT clock_timestamp(), manifest jsonb NOT NULL)""",
    """CREATE TABLE provenance.ingestion_attempt (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES provenance.source_dataset,
        started_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
        mode text NOT NULL, status text NOT NULL, artifact_sha256 text, raw_object_key text, detail text,
        observed_on date NOT NULL, run_id uuid)""",
    """CREATE TABLE provenance.ingestion_run (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES provenance.source_dataset,
        input_fingerprint text NOT NULL, mapping_version text NOT NULL, manifest jsonb NOT NULL,
        observed_on date NOT NULL, published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        raw_object_key text NOT NULL, artifact_sha256 text NOT NULL, metrics jsonb NOT NULL,
        UNIQUE (dataset_id,input_fingerprint,mapping_version))""",
    """ALTER TABLE provenance.ingestion_attempt ADD FOREIGN KEY (run_id) REFERENCES provenance.ingestion_run""",
    """CREATE TABLE provenance.source_record (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES provenance.ingestion_run,
        external_record_id text NOT NULL, content_sha256 text NOT NULL, locator jsonb NOT NULL)""",
    """CREATE INDEX source_record_run ON provenance.source_record(run_id)""",
    """CREATE TABLE staging.review_item (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), attempt_id uuid NOT NULL REFERENCES provenance.ingestion_attempt,
        source_record_id uuid REFERENCES provenance.source_record, reason text NOT NULL, locator jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    """CREATE TABLE core.jurisdiction (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), county_fips text NOT NULL UNIQUE,
        county_name text NOT NULL, state_code text NOT NULL)""",
    """CREATE TABLE core.parcel (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), jurisdiction_id uuid NOT NULL REFERENCES core.jurisdiction,
        primary_pin text NOT NULL, normalized_pin text NOT NULL,
        parcel_state text NOT NULL DEFAULT 'active' CHECK(parcel_state IN ('active','pending_review','retired')))""",
    """CREATE UNIQUE INDEX parcel_active_pin ON core.parcel(jurisdiction_id,normalized_pin)
        WHERE parcel_state <> 'retired'""",
    """CREATE TABLE core.parcel_identifier (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parcel_id uuid NOT NULL REFERENCES core.parcel,
        dataset_id uuid NOT NULL REFERENCES provenance.source_dataset, identifier_type text NOT NULL,
        identifier_value text NOT NULL, normalized_value text NOT NULL, is_current boolean NOT NULL DEFAULT true,
        source_record_id uuid NOT NULL REFERENCES provenance.source_record,
        first_seen date NOT NULL, last_seen date NOT NULL)""",
    """CREATE UNIQUE INDEX active_parcel_alias ON core.parcel_identifier
        (dataset_id, identifier_type, normalized_value) WHERE is_current""",
    """CREATE INDEX parcel_alias_lookup ON core.parcel_identifier(parcel_id,identifier_type)""",
    """CREATE TABLE core.parcel_lineage (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), predecessor_id uuid NOT NULL REFERENCES core.parcel,
        successor_id uuid NOT NULL REFERENCES core.parcel, source_record_id uuid NOT NULL REFERENCES provenance.source_record,
        CHECK(predecessor_id <> successor_id), UNIQUE(predecessor_id,successor_id,source_record_id))""",
    """CREATE TABLE core.parcel_geometry_version (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parcel_id uuid NOT NULL REFERENCES core.parcel,
        source_record_id uuid NOT NULL REFERENCES provenance.source_record,
        geom geometry(MultiPolygon,4326) NOT NULL CHECK(NOT ST_IsEmpty(geom) AND ST_IsValid(geom)),
        observed_at timestamptz NOT NULL, is_current boolean NOT NULL,
        primary_pin text NOT NULL, normalized_pin text NOT NULL,address text)""",
    """CREATE UNIQUE INDEX one_current_geometry ON core.parcel_geometry_version(parcel_id) WHERE is_current""",
    """CREATE INDEX current_geometry_gist ON core.parcel_geometry_version USING gist(geom) WHERE is_current""",
    """CREATE TABLE core.address (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), raw_address text NOT NULL, normalized_address text NOT NULL,
        parcel_id uuid NOT NULL REFERENCES core.parcel, source_record_id uuid NOT NULL REFERENCES provenance.source_record)""",
    """CREATE TABLE core.property (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text, asset_class text NOT NULL DEFAULT 'unknown',
        property_status text NOT NULL DEFAULT 'active')""",
    """CREATE TABLE core.property_parcel (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), property_id uuid NOT NULL REFERENCES core.property,
        parcel_id uuid NOT NULL REFERENCES core.parcel, relationship_type text NOT NULL DEFAULT 'component',
        valid_from date,valid_to date, CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
        EXCLUDE USING gist(property_id WITH =,parcel_id WITH =,relationship_type WITH =,
             daterange(valid_from,valid_to,'[)') WITH &&))""",
    """CREATE TABLE core.building (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),property_id uuid NOT NULL REFERENCES core.property,
        name text,gross_area numeric CHECK(gross_area>=0),year_built integer)""",
    """CREATE TABLE core.party (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), party_type text NOT NULL
        CHECK(party_type IN ('person','organization','unknown')), canonical_name text NOT NULL)""",
    """CREATE TABLE core.entity_registration (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),party_id uuid NOT NULL REFERENCES core.party,
        jurisdiction_code text NOT NULL,registration_number text NOT NULL,legal_name text NOT NULL,
        source_record_id uuid NOT NULL REFERENCES provenance.source_record,UNIQUE(jurisdiction_code,registration_number))""",
    """CREATE TABLE evidence.claim (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),subject_id uuid NOT NULL,subject_type text NOT NULL,
        predicate text NOT NULL,value jsonb NOT NULL,verification_state text NOT NULL CHECK(
        verification_state IN ('candidate','verified','corroborated','conflicted','stale','unresolved')),
        valid_from date, valid_to date, observed_at timestamptz NOT NULL,extraction_method text NOT NULL,
        supersedes_claim_id uuid REFERENCES evidence.claim)""",
    """CREATE INDEX claim_subject ON evidence.claim(subject_id,predicate,observed_at DESC)""",
    """CREATE TABLE evidence.claim_support (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),claim_id uuid NOT NULL REFERENCES evidence.claim,
        source_record_id uuid NOT NULL REFERENCES provenance.source_record,locator jsonb NOT NULL,
        UNIQUE(claim_id,source_record_id))""",
    """CREATE TABLE evidence.claim_review_event (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),claim_id uuid NOT NULL REFERENCES evidence.claim,
        reviewer text NOT NULL,decision text NOT NULL,reason text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    """CREATE TABLE core.party_relationship (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),subject_party_id uuid NOT NULL REFERENCES core.party,
        object_party_id uuid NOT NULL REFERENCES core.party,relationship_type text NOT NULL,
        valid_from date,valid_to date,claim_id uuid NOT NULL REFERENCES evidence.claim)""",
    """CREATE TABLE core.ownership_record (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),parcel_id uuid NOT NULL REFERENCES core.parcel,
        party_id uuid NOT NULL REFERENCES core.party,ownership_kind text NOT NULL,
        claim_id uuid NOT NULL REFERENCES evidence.claim,observed_on date NOT NULL)""",
    """CREATE VIEW provenance.visible_source_record WITH (security_barrier=true) AS
        SELECT s.id AS source_record_id, s.locator, d.dataset_key, r.observed_on, d.export_allowed
        FROM provenance.source_record s JOIN provenance.ingestion_run r ON r.id=s.run_id
        JOIN provenance.source_dataset d ON d.id=r.dataset_id
        WHERE d.enabled AND d.shared_display""",
    """CREATE VIEW core.visible_parcel WITH (security_barrier=true) AS
        SELECT p.id,p.jurisdiction_id,j.county_fips,g.primary_pin,g.normalized_pin,g.address,g.geom,
               g.observed_at,g.source_record_id,s.dataset_key,s.export_allowed
        FROM core.parcel p JOIN core.jurisdiction j ON j.id=p.jurisdiction_id
        JOIN core.parcel_geometry_version g ON g.parcel_id=p.id AND g.is_current
        JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id
        WHERE p.parcel_state='active'""",
    """CREATE VIEW evidence.visible_claim WITH (security_barrier=true) AS
        SELECT c.id,c.subject_id,c.subject_type,c.predicate,c.value,c.verification_state,c.observed_at,
               s.source_record_id,cs.locator,s.dataset_key,s.export_allowed
        FROM evidence.claim c JOIN evidence.claim_support cs ON cs.claim_id=c.id
        JOIN provenance.visible_source_record s ON s.source_record_id=cs.source_record_id""",
    """CREATE FUNCTION provenance.forbid_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'immutable history'; END $$""",
    *[
        f"""CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table}
           FOR EACH ROW EXECUTE FUNCTION provenance.forbid_rewrite()"""
        for table in (
            "provenance.manifest_event",
            "provenance.source_record",
            "evidence.claim",
            "evidence.claim_support",
            "evidence.claim_review_event",
        )
    ],
]
