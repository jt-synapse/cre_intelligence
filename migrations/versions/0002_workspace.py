"""Workspace membership, private saves, evidence-qualified screening, and property grouping."""

from alembic import op

revision = "0002_workspace"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

DDL = [
    "CREATE TABLE operations.organization(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text NOT NULL)",
    """CREATE TABLE operations.membership(org_id uuid NOT NULL REFERENCES operations.organization,
       subject text NOT NULL, role text NOT NULL CHECK(role IN ('admin','researcher','analyst','viewer')),
       PRIMARY KEY(org_id,subject))""",
    "CREATE INDEX membership_subject ON operations.membership(subject)",
    "CREATE TABLE operations.curator(subject text PRIMARY KEY)",
    """CREATE TABLE operations.saved_property(org_id uuid NOT NULL REFERENCES operations.organization,
       property_id uuid NOT NULL REFERENCES core.property,subject text NOT NULL,
       saved_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(org_id,property_id))""",
    """CREATE TABLE operations.portfolio(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL
       REFERENCES operations.organization, name text NOT NULL, UNIQUE(org_id,id),UNIQUE(org_id,name))""",
    """CREATE TABLE operations.portfolio_property(org_id uuid NOT NULL,portfolio_id uuid NOT NULL,
       property_id uuid NOT NULL REFERENCES core.property,
       PRIMARY KEY(org_id,portfolio_id,property_id),
       FOREIGN KEY(org_id,portfolio_id) REFERENCES operations.portfolio(org_id,id))""",
    """CREATE TABLE operations.audit_event(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
       org_id uuid NOT NULL REFERENCES operations.organization,subject text NOT NULL,action text NOT NULL,
       resource_id text NOT NULL,detail jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON operations.audit_event
       FOR EACH ROW EXECUTE FUNCTION provenance.forbid_rewrite()""",
    """CREATE TABLE core.property_alias(old_id uuid PRIMARY KEY REFERENCES core.property,
       current_id uuid NOT NULL REFERENCES core.property,CHECK(old_id <> current_id),
       changed_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE FUNCTION core.current_property_id(input uuid) RETURNS uuid LANGUAGE sql STABLE AS $$
       WITH RECURSIVE chain(id) AS (SELECT input UNION
          SELECT a.current_id FROM core.property_alias a JOIN chain c ON a.old_id=c.id)
       SELECT id FROM chain WHERE NOT EXISTS(SELECT 1 FROM core.property_alias WHERE old_id=chain.id) $$""",
    """CREATE TABLE core.screening_layer(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
       dataset_key text NOT NULL,kind text NOT NULL CHECK(kind IN ('zoning','environmental','flood')),
       reference text NOT NULL, observed_on date NOT NULL, object_key text NOT NULL, rights_reference text NOT NULL,
       shared_display boolean NOT NULL,export_allowed boolean NOT NULL,
       coverage geometry(MultiPolygon,4326) CHECK(ST_IsValid(coverage)),active boolean NOT NULL DEFAULT true,
       UNIQUE(dataset_key,observed_on,object_key))""",
    "CREATE UNIQUE INDEX active_screening_layer ON core.screening_layer(dataset_key) WHERE active",
    """CREATE TABLE core.screening_feature(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
       layer_id uuid NOT NULL REFERENCES core.screening_layer, label text NOT NULL, locator text NOT NULL,
       geom geometry(Geometry,4326) NOT NULL CHECK(ST_IsValid(geom) AND NOT ST_IsEmpty(geom)))""",
    "CREATE INDEX screening_geometry ON core.screening_feature USING gist(geom)",
    """CREATE VIEW core.visible_screening_layer WITH(security_barrier=true) AS
       SELECT id,dataset_key,kind,reference,observed_on,coverage,export_allowed
       FROM core.screening_layer WHERE active AND shared_display""",
    """CREATE VIEW core.visible_screening_feature WITH(security_barrier=true) AS
       SELECT f.* FROM core.screening_feature f JOIN core.visible_screening_layer l ON f.layer_id=l.id""",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)
    for name in (
        "saved_property",
        "portfolio",
        "portfolio_property",
        "audit_event",
        "membership",
        "organization",
        "curator",
    ):
        op.execute(f"ALTER TABLE operations.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE operations.{name} FORCE ROW LEVEL SECURITY")
    for name in ("membership", "organization", "curator"):
        op.execute(
            f"CREATE POLICY directory_operator ON operations.{name} TO CURRENT_USER USING(true) WITH CHECK(true)"
        )
    for name in ("saved_property", "portfolio", "portfolio_property", "audit_event"):
        op.execute(f"""CREATE POLICY tenant_scope ON operations.{name} USING
            (org_id=nullif(current_setting('app.org_id',true),'')::uuid) WITH CHECK
            (org_id=nullif(current_setting('app.org_id',true),'')::uuid)""")
    op.execute("""CREATE POLICY self ON operations.membership FOR SELECT
                  USING(subject=current_setting('app.subject',true))""")
    op.execute("""CREATE POLICY self ON operations.curator FOR SELECT
                  USING(subject=current_setting('app.subject',true))""")
    op.execute("""CREATE POLICY member_org ON operations.organization FOR SELECT USING(
                  EXISTS(SELECT 1 FROM operations.membership m WHERE m.org_id=id))""")


def downgrade():
    op.execute("DROP VIEW core.visible_screening_feature,core.visible_screening_layer")
    op.execute("DROP TABLE core.screening_feature,core.screening_layer")
    op.execute("DROP FUNCTION core.current_property_id(uuid)")
    op.execute("DROP TABLE core.property_alias")
    op.execute(
        "DROP TABLE operations.portfolio_property,operations.saved_property,operations.audit_event"
    )
    op.execute(
        "DROP TABLE operations.portfolio,operations.curator,operations.membership,operations.organization"
    )
