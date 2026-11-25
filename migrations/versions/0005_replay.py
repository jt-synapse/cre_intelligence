"""Keep per-attempt quality reports and track resolutions of unmatched rows."""

from alembic import op

revision = "0005_replay"
down_revision = "0004_citations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE provenance.ingestion_attempt ADD COLUMN quality jsonb")
    op.execute("""UPDATE provenance.ingestion_attempt a SET quality=r.metrics
        FROM provenance.ingestion_run r WHERE a.run_id=r.id""")
    op.execute("""CREATE TABLE staging.review_resolution (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),review_item_id uuid NOT NULL UNIQUE REFERENCES staging.review_item,
        attempt_id uuid NOT NULL REFERENCES provenance.ingestion_attempt, reason text NOT NULL,
        resolved_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
    op.execute("""CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON staging.review_resolution
        FOR EACH ROW EXECUTE FUNCTION provenance.forbid_rewrite()""")


def downgrade():
    op.execute("DROP TABLE staging.review_resolution")
    op.execute("ALTER TABLE provenance.ingestion_attempt DROP COLUMN quality")
