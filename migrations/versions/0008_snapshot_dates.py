"""Scope source replays to an observation date and retain point-in-time parcel citations."""

from alembic import op

revision = "0008_snapshot_dates"
down_revision = "0007_workflow_review"
branch_labels = None
depends_on = None

OLD_KEY = "ingestion_run_dataset_id_input_fingerprint_mapping_version_key"


def upgrade():
    op.drop_constraint(OLD_KEY, "ingestion_run", schema="provenance", type_="unique")
    op.create_unique_constraint(
        "ingestion_run_dated_snapshot",
        "ingestion_run",
        ["dataset_id", "observed_on", "mapping_version", "input_fingerprint"],
        schema="provenance",
    )
    op.execute("""CREATE INDEX parcel_geometry_observation
        ON core.parcel_geometry_version(parcel_id,observed_at DESC)""")
    # Legacy replays retained their original objects. Queue a normal authorized retry
    # instead of requiring the migration credential to have access to object storage.
    op.execute("""INSERT INTO staging.review_item(attempt_id,reason,locator)
        SELECT a.id,'retry retained snapshot at its original observation date',
               jsonb_build_object('observed_on',a.observed_on,'previous_run_id',r.id)
        FROM provenance.ingestion_attempt a JOIN provenance.ingestion_run r ON r.id=a.run_id
        WHERE a.observed_on<>r.observed_on AND a.raw_object_key IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM staging.review_item q WHERE q.attempt_id=a.id
                          AND q.reason='retry retained snapshot at its original observation date')""")


def downgrade():
    # Restoring the old key will safely fail if distinct dated observations
    # already share a fingerprint. No historical records are removed.
    op.create_unique_constraint(
        OLD_KEY,
        "ingestion_run",
        ["dataset_id", "input_fingerprint", "mapping_version"],
        schema="provenance",
    )
    op.drop_constraint(
        "ingestion_run_dated_snapshot",
        "ingestion_run",
        schema="provenance",
        type_="unique",
    )
    op.execute("DROP INDEX core.parcel_geometry_observation")
