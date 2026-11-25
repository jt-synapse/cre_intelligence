"""Expose approved citation metadata with each visible source reference."""

from alembic import op

revision = "0004_citations"
down_revision = "0003_workflows"
branch_labels = None
depends_on = None

SOURCE = """SELECT s.id AS source_record_id,s.locator,d.dataset_key,r.observed_on,d.export_allowed"""
SOURCE_FROM = """ FROM provenance.source_record s JOIN provenance.ingestion_run r ON r.id=s.run_id
    JOIN provenance.source_dataset d ON d.id=r.dataset_id WHERE d.enabled AND d.shared_display"""
CLAIM = """SELECT c.id,c.subject_id,c.subject_type,c.predicate,c.value,{} AS verification_state,
    c.observed_at,s.source_record_id,cs.locator,s.dataset_key,s.export_allowed"""
CLAIM_FROM = """ FROM evidence.claim c JOIN evidence.claim_support cs ON cs.claim_id=c.id
    JOIN provenance.visible_source_record s ON s.source_record_id=cs.source_record_id"""
PARCEL = """SELECT p.id,p.jurisdiction_id,j.county_fips,g.primary_pin,g.normalized_pin,g.address,g.geom,
    g.observed_at,g.source_record_id,s.dataset_key,s.export_allowed"""
PARCEL_FROM = """ FROM core.parcel p JOIN core.jurisdiction j ON j.id=p.jurisdiction_id
    JOIN core.parcel_geometry_version g ON g.parcel_id=p.id AND g.is_current
    JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id WHERE p.parcel_state='active'"""


def upgrade():
    op.execute(
        "CREATE OR REPLACE VIEW provenance.visible_source_record WITH(security_barrier=true) AS "
        + SOURCE
        + """,r.manifest->>'publisher' AS publisher,
              r.manifest->>'origin' AS source_origin,
              d.manifest->'rights'->>'attribution' AS attribution,s.content_sha256,r.id AS run_id"""
        + SOURCE_FROM
    )
    citation = ",s.publisher,s.source_origin,s.attribution,s.content_sha256,s.run_id"
    # Only other visible source records can affect the displayed conflict state.
    op.execute(
        "CREATE OR REPLACE VIEW evidence.visible_claim WITH(security_barrier=true) AS "
        + CLAIM.format("""coalesce((SELECT e.decision FROM evidence.claim_review_event e
                            WHERE e.claim_id=c.id AND e.decision IN ('verified','corroborated','conflicted','stale','unresolved','candidate')
                            ORDER BY e.created_at DESC,e.id DESC LIMIT 1),
                          CASE WHEN c.predicate='assessor_listed_owner' AND EXISTS (
                            SELECT 1 FROM evidence.claim other JOIN evidence.claim_support cs2 ON cs2.claim_id=other.id
                            JOIN provenance.visible_source_record s2 ON s2.source_record_id=cs2.source_record_id
                            WHERE other.subject_type=c.subject_type AND other.subject_id=c.subject_id
                            AND other.predicate=c.predicate AND other.observed_at=c.observed_at
                            AND upper(trim(other.value->>'value'))<>upper(trim(c.value->>'value')))
                          THEN 'conflicted' ELSE c.verification_state END)""")
        + citation
        + CLAIM_FROM
    )
    op.execute(
        "CREATE OR REPLACE VIEW core.visible_parcel WITH(security_barrier=true) AS "
        + PARCEL
        + citation
        + PARCEL_FROM
    )
    op.execute(
        "CREATE INDEX claim_review_history ON evidence.claim_review_event(claim_id,created_at DESC)"
    )


def downgrade():
    # PostgreSQL cannot remove columns using CREATE OR REPLACE. Keep the additive
    # metadata columns for older clients and restore the earlier state calculation.
    op.execute(
        "CREATE OR REPLACE VIEW evidence.visible_claim WITH(security_barrier=true) AS "
        + CLAIM.format("c.verification_state")
        + ",s.publisher,s.source_origin,s.attribution,s.content_sha256,s.run_id"
        + CLAIM_FROM
    )
    op.execute("DROP INDEX evidence.claim_review_history")
