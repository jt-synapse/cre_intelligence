"""Tenant-scoped field folders, saved parcel pins and visit history."""

from alembic import op

revision = "0012_field_places"
down_revision = "0011_field_sites"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE operations.field_folder (
        org_id uuid NOT NULL REFERENCES operations.organization,
        id uuid NOT NULL DEFAULT gen_random_uuid(), name text NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
        color text NOT NULL CHECK(color IN ('teal','blue','amber','violet','rose','slate')),
        PRIMARY KEY(org_id,id))""")
    op.execute(
        "CREATE UNIQUE INDEX field_folder_name ON operations.field_folder(org_id,lower(name))"
    )
    op.execute("""CREATE TABLE operations.field_pin (
        org_id uuid NOT NULL REFERENCES operations.organization,parcel_id uuid NOT NULL REFERENCES core.parcel,
        label text NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 120),folder_id uuid,
        PRIMARY KEY(org_id,parcel_id),FOREIGN KEY(org_id,folder_id) REFERENCES operations.field_folder)""")
    op.execute("""CREATE TABLE operations.field_visit (
        org_id uuid NOT NULL REFERENCES operations.organization,parcel_id uuid NOT NULL REFERENCES core.parcel,
        created_by text NOT NULL,operation_id uuid NOT NULL,visited_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(org_id,created_by,operation_id))""")
    op.execute(
        "CREATE INDEX parcel_visits ON operations.field_visit(org_id,parcel_id,visited_at DESC)"
    )
    op.execute("""CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON operations.field_visit
        FOR EACH ROW EXECUTE FUNCTION provenance.forbid_rewrite()""")
    for name in ("field_folder", "field_pin", "field_visit"):
        op.execute(f"ALTER TABLE operations.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE operations.{name} FORCE ROW LEVEL SECURITY")
        scope = "org_id=nullif(current_setting('app.org_id',true),'')::uuid"
        if name != "field_folder":
            scope += (
                " AND EXISTS(SELECT FROM core.visible_parcel v WHERE v.id=parcel_id)"
            )
        write = scope
        if name == "field_visit":
            write += " AND created_by=current_setting('app.subject',true)"
        op.execute(
            f"CREATE POLICY tenant_scope ON operations.{name} USING ({scope}) WITH CHECK ({write})"
        )


def downgrade():
    op.execute(
        "DROP TABLE operations.field_visit,operations.field_pin,operations.field_folder"
    )
