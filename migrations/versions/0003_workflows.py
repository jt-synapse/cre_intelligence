"""Tenant-owned investigations, evidence reviews, operating records and dossiers."""

from alembic import op

revision = "0003_workflows"
down_revision = "0002_workspace"
branch_labels = None
depends_on = None

TABLES = {
    "document": """
        name text NOT NULL, kind text NOT NULL, media_type text NOT NULL, object_key text NOT NULL,
        sha256 char(64) NOT NULL, byte_size bigint NOT NULL CHECK(byte_size > 0),
        exportable boolean NOT NULL DEFAULT false, allow_ai boolean NOT NULL DEFAULT false,
        supersedes_id uuid, FOREIGN KEY (org_id,supersedes_id) REFERENCES operations.document(org_id,id)""",
    "investigation": """
        objective text NOT NULL, preferred_roles jsonb NOT NULL, max_requests int NOT NULL,
        max_tokens int NOT NULL, requests_used int NOT NULL DEFAULT 0, tokens_used int NOT NULL DEFAULT 0,
        status text NOT NULL DEFAULT 'queued', outcome text, limitation text, owner_evidence jsonb NOT NULL DEFAULT '[]'""",
    "investigation_step": """
        investigation_id uuid NOT NULL, name text NOT NULL, detail jsonb NOT NULL,
        FOREIGN KEY (org_id,investigation_id) REFERENCES operations.investigation(org_id,id)""",
    "finding": """
        investigation_id uuid NOT NULL, kind text NOT NULL, subject text NOT NULL, assertion text NOT NULL,
        reference text NOT NULL, locator text NOT NULL, relationship text, channel_kind text,
        identity_finding_id uuid, channel_value text, document_id uuid, exportable boolean NOT NULL DEFAULT false, method text NOT NULL,
        source_hash char(64) NOT NULL, source_excerpt text, effective_date date,
        FOREIGN KEY (org_id,investigation_id) REFERENCES operations.investigation(org_id,id),
        FOREIGN KEY (org_id,document_id) REFERENCES operations.document(org_id,id),
        FOREIGN KEY (org_id,identity_finding_id) REFERENCES operations.finding(org_id,id)""",
    "finding_review": """
        finding_id uuid NOT NULL, decision text NOT NULL, reason text NOT NULL, correction text,
        ordinal integer NOT NULL, UNIQUE(finding_id, ordinal),
        FOREIGN KEY (org_id,finding_id) REFERENCES operations.finding(org_id,id)""",
    "opportunity": """title text NOT NULL, stage text NOT NULL, assignee text""",
    "activity": """
        opportunity_id uuid NOT NULL, kind text NOT NULL, body text NOT NULL, assignee text, document_id uuid,
        FOREIGN KEY (org_id,opportunity_id) REFERENCES operations.opportunity(org_id,id),
        FOREIGN KEY (org_id,document_id) REFERENCES operations.document(org_id,id)""",
    "analysis_scenario": """
        name text NOT NULL, period text NOT NULL, currency text NOT NULL, assumptions text NOT NULL,
        model_version text NOT NULL, inputs jsonb NOT NULL, outputs jsonb NOT NULL, sources jsonb NOT NULL""",
    "report": """
        status text NOT NULL, snapshot jsonb NOT NULL, digest char(64) NOT NULL, object_key text,
        pdf_hash char(64), decision_reason text, reviewer text, reviewed_at timestamptz""",
    "suppression": """channel text NOT NULL, reason text NOT NULL, UNIQUE(org_id,channel)""",
    "outreach_draft": """
        investigation_id uuid NOT NULL, channel_finding_id uuid NOT NULL, channel text NOT NULL,
        body text NOT NULL, status text NOT NULL, reviewer text,
        FOREIGN KEY (org_id,investigation_id) REFERENCES operations.investigation(org_id,id),
        FOREIGN KEY (org_id,channel_finding_id) REFERENCES operations.finding(org_id,id)""",
    "workflow_job": """
        kind text NOT NULL CHECK(kind IN ('investigate','render_report')), target_id uuid NOT NULL,
        attempts int NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'queued',
        available_at timestamptz NOT NULL DEFAULT now(), detail text,
        UNIQUE(org_id,kind,target_id)""",
}


def upgrade():
    for name, definition in TABLES.items():
        op.execute(f"""CREATE TABLE operations.{name} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES operations.organization(id),
            property_id uuid NOT NULL REFERENCES core.property(id),
            created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(org_id,id), {definition})""")
        op.execute(f"CREATE INDEX ON operations.{name}(org_id,property_id)")
        op.execute(f"ALTER TABLE operations.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE operations.{name} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_scope ON operations.{name}
            USING (org_id = nullif(current_setting('app.org_id',true),'')::uuid)
            WITH CHECK (org_id = nullif(current_setting('app.org_id',true),'')::uuid)""")
    op.execute("""CREATE INDEX workflow_ready ON operations.workflow_job(org_id,available_at)
        WHERE status='queued'""")
    op.execute("""CREATE FUNCTION operations.workflow_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable workflow record'; END $$""")
    for name in (
        "finding",
        "finding_review",
        "investigation_step",
        "activity",
        "analysis_scenario",
    ):
        op.execute(f"""CREATE TRIGGER immutable BEFORE UPDATE ON operations.{name}
            FOR EACH ROW EXECUTE FUNCTION operations.workflow_immutable()""")


def downgrade():
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE operations.{name}")
    op.execute("DROP FUNCTION operations.workflow_immutable()")
