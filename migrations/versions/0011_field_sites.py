"""Organization-owned sites with immutable revisions and source references."""

from alembic import op

revision = "0011_field_sites"
down_revision = "0010_field_capture"
branch_labels = None
depends_on = None

TABLES = ("field_site", "field_site_revision", "field_site_member", "field_site_claim")


def upgrade():
    op.execute(
        "CREATE INDEX reader_version_membership ON core.reader_parcel(geometry_version_id,parcel_id)"
    )
    op.execute("""CREATE VIEW core.visible_field_geometry WITH (security_barrier=true) AS
        SELECT g.parcel_id,g.id AS geometry_version_id,g.geom,g.primary_pin,g.observed_at,
               s.source_record_id,s.run_id,s.dataset_key,s.publisher,s.attribution,s.locator
        FROM core.parcel_geometry_version g
        JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id
        WHERE EXISTS (SELECT FROM core.reader_parcel rp WHERE rp.parcel_id=g.parcel_id
                      AND rp.geometry_version_id=g.id)""")
    op.execute("""CREATE TABLE operations.field_site (
        org_id uuid NOT NULL REFERENCES operations.organization,
        id uuid NOT NULL DEFAULT gen_random_uuid(), current_revision integer NOT NULL CHECK(current_revision>0),
        PRIMARY KEY(org_id,id))""")
    op.execute("""CREATE TABLE operations.field_site_revision (
        org_id uuid NOT NULL,site_id uuid NOT NULL,revision integer NOT NULL CHECK(revision>0),
        name text NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 200),
        reader_version uuid NOT NULL,created_by text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(org_id,site_id,revision),
        FOREIGN KEY(org_id,site_id) REFERENCES operations.field_site(org_id,id))""")
    op.execute("""ALTER TABLE operations.field_site ADD FOREIGN KEY(org_id,id,current_revision)
        REFERENCES operations.field_site_revision(org_id,site_id,revision) DEFERRABLE INITIALLY DEFERRED""")
    op.execute("""CREATE TABLE operations.field_site_member (
        org_id uuid NOT NULL,site_id uuid NOT NULL,revision integer NOT NULL,
        ordinal smallint NOT NULL CHECK(ordinal BETWEEN 1 AND 20),
        parcel_id uuid NOT NULL REFERENCES core.parcel,
        geometry_version_id uuid NOT NULL REFERENCES core.parcel_geometry_version,
        PRIMARY KEY(org_id,site_id,revision,parcel_id),UNIQUE(org_id,site_id,revision,ordinal),
        FOREIGN KEY(org_id,site_id,revision) REFERENCES operations.field_site_revision)""")
    op.execute("""CREATE TABLE operations.field_site_claim (
        org_id uuid NOT NULL,site_id uuid NOT NULL,revision integer NOT NULL,parcel_id uuid NOT NULL,
        claim_id uuid NOT NULL,source_record_id uuid NOT NULL,
        PRIMARY KEY(org_id,site_id,revision,parcel_id,claim_id,source_record_id),
        FOREIGN KEY(org_id,site_id,revision,parcel_id) REFERENCES operations.field_site_member,
        FOREIGN KEY(claim_id,source_record_id) REFERENCES evidence.claim_support(claim_id,source_record_id))""")
    for table in TABLES:
        op.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE operations.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_scope ON operations.{table}
            USING(org_id=nullif(current_setting('app.org_id',true),'')::uuid)
            WITH CHECK(org_id=nullif(current_setting('app.org_id',true),'')::uuid)""")
        if table != "field_site":
            op.execute(f"""CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON operations.{table}
                FOR EACH ROW EXECUTE FUNCTION provenance.forbid_rewrite()""")


def downgrade():
    op.execute("DROP TABLE " + ",".join(f"operations.{t}" for t in reversed(TABLES)))
    op.execute("DROP VIEW core.visible_field_geometry")
    op.execute("DROP INDEX core.reader_version_membership")
