"""Indexes for pilot search, monitoring and point-in-time review."""

from alembic import op

revision = "0006_operations_health"
down_revision = "0005_replay"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""CREATE INDEX current_parcel_address_search ON core.parcel_geometry_version
               USING gin(lower(address) gin_trgm_ops) WHERE is_current""")
    op.execute(
        """CREATE INDEX source_attempt_health ON provenance.ingestion_attempt(dataset_id,started_at DESC)"""
    )
    op.execute(
        """CREATE INDEX tenant_job_health ON operations.workflow_job(org_id,status,created_at)"""
    )
    op.execute(
        """CREATE INDEX tenant_audit_time ON operations.audit_event(org_id,created_at DESC)"""
    )


def downgrade():
    for index in (
        "operations.tenant_audit_time",
        "operations.tenant_job_health",
        "provenance.source_attempt_health",
        "core.current_parcel_address_search",
    ):
        op.execute(f"DROP INDEX {index}")
