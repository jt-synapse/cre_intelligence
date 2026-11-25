"""Immutable workspace field captures and actor-scoped replay receipts."""

from alembic import op

revision = "0010_field_capture"
down_revision = "0009_parcel_version"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE operations.field_capture (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id uuid NOT NULL REFERENCES operations.organization(id),
        parcel_id uuid NOT NULL REFERENCES core.parcel(id),
        created_by text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        operation_id uuid NOT NULL,
        note text NOT NULL CHECK (length(note) <= 4000),
        object_key text CHECK (object_key ~ '^[0-9a-f]{64}$'),
        photo_type text CHECK (photo_type IN ('image/jpeg','image/png','image/webp')),
        CHECK ((object_key IS NULL) = (photo_type IS NULL)),
        CHECK (length(trim(note)) > 0 OR object_key IS NOT NULL),
        UNIQUE (org_id, created_by, operation_id))""")
    op.execute("""CREATE INDEX field_capture_parcel ON operations.field_capture
        (org_id, parcel_id, created_at DESC, id DESC)""")
    op.execute("ALTER TABLE operations.field_capture ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operations.field_capture FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY visible_captures ON operations.field_capture FOR SELECT USING (
        org_id = nullif(current_setting('app.org_id',true),'')::uuid AND
        EXISTS (SELECT 1 FROM core.visible_parcel v WHERE v.id = parcel_id))""")
    op.execute("""CREATE POLICY write_captures ON operations.field_capture FOR INSERT WITH CHECK (
        org_id = nullif(current_setting('app.org_id',true),'')::uuid AND
        created_by = current_setting('app.subject',true) AND
        EXISTS (SELECT 1 FROM core.visible_parcel v WHERE v.id = parcel_id))""")


def downgrade():
    op.execute("DROP TABLE operations.field_capture")
