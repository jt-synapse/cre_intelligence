"""Append-only review typing and access to export-entitled historical screening versions."""

from alembic import op

revision = "0007_workflow_review"
down_revision = "0006_operations_health"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""ALTER TABLE operations.finding_review ADD COLUMN typed_evidence jsonb
                  CHECK (typed_evidence IS NULL OR jsonb_typeof(typed_evidence)='object')""")
    op.execute("""CREATE VIEW core.exportable_screening_version WITH (security_barrier=true) AS
        SELECT version.id,version.dataset_key,version.reference,version.observed_on,version.kind,
               version.object_key AS content_sha256
        FROM core.screening_layer version WHERE version.shared_display AND version.export_allowed
          AND EXISTS (SELECT 1 FROM core.screening_layer live WHERE live.dataset_key=version.dataset_key
                      AND live.active AND live.shared_display AND live.export_allowed)""")


def downgrade():
    op.execute("DROP VIEW core.exportable_screening_version")
    op.execute("ALTER TABLE operations.finding_review DROP COLUMN typed_evidence")
