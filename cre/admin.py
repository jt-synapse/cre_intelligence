"""Operator commands. Use a migration/administrative credential apart from API processes."""

import argparse
import os
from uuid import UUID

from sqlalchemy import create_engine, text


def admin_engine():
    return create_engine(
        os.environ.get("CRE_MIGRATION_URL") or os.environ["DATABASE_URL"]
    )


def grant_runtime(conn, role_name, worker):
    # Identifiers use dialect quoting; database roles are provisioned by the operator.
    role = conn.dialect.identifier_preparer.quote_identifier(role_name)
    flags = conn.execute(
        text("""select rolsuper,rolbypassrls,not rolcanlogin,pg_has_role(oid,
                 (select relowner from pg_class where oid='operations.organization'::regclass),'MEMBER')
                 from pg_roles where rolname=:r"""),
        {"r": role_name},
    ).first()
    if flags is None or any(flags):
        raise ValueError(
            "Supply a login role without superuser, BYPASSRLS or membership in the schema owner"
        )
    conn.exec_driver_sql(
        f"GRANT USAGE ON SCHEMA core,evidence,operations,provenance TO {role}"
    )
    conn.exec_driver_sql(f"""GRANT SELECT ON core.visible_parcel,core.visible_screening_layer,
         core.visible_screening_feature,core.exportable_screening_version,core.property,core.property_alias,core.property_parcel,
         provenance.visible_source_record,evidence.visible_claim,evidence.reader_parcel_claim,evidence.reader_owner,evidence.reader_control,operations.organization TO {role}""")
    conn.exec_driver_sql(
        f"GRANT EXECUTE ON FUNCTION core.current_property_id(uuid) TO {role}"
    )
    workflow_read = (
        "document",
        "investigation",
        "investigation_step",
        "finding",
        "finding_review",
        "opportunity",
        "activity",
        "analysis_scenario",
        "report",
        "suppression",
        "outreach_draft",
        "workflow_job",
    )
    for name in workflow_read:
        conn.exec_driver_sql(f"GRANT SELECT ON operations.{name} TO {role}")
    conn.exec_driver_sql(f"GRANT INSERT ON operations.audit_event TO {role}")
    if not worker:
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT ON operations.field_folder,operations.field_visit TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT,UPDATE(label,folder_id) ON operations.field_pin TO {role}"
        )
        conn.exec_driver_sql(f"GRANT SELECT ON core.visible_field_geometry TO {role}")
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT ON operations.field_capture,operations.field_site_revision,operations.field_site_member,operations.field_site_claim TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT,UPDATE(current_revision) ON operations.field_site TO {role}"
        )
        conn.exec_driver_sql(f"GRANT INSERT ON evidence.claim_review_event TO {role}")
    if worker:
        conn.exec_driver_sql(
            "DROP POLICY IF EXISTS worker_directory ON operations.organization"
        )
        conn.exec_driver_sql(
            f"CREATE POLICY worker_directory ON operations.organization FOR SELECT TO {role} USING(true)"
        )
        inserts = ("investigation_step", "finding")
        updates = ("investigation", "workflow_job", "report")
    else:
        conn.exec_driver_sql(
            f"GRANT SELECT ON operations.membership,operations.curator TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT ON operations.saved_property,operations.portfolio_property TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT SELECT,INSERT,UPDATE(name) ON operations.portfolio TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT INSERT ON core.property,core.property_parcel,core.property_alias TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT UPDATE(name,property_status) ON core.property TO {role}"
        )
        conn.exec_driver_sql(
            f"GRANT UPDATE(valid_to) ON core.property_parcel TO {role}"
        )
        inserts = workflow_read
        updates = (
            "document",
            "investigation",
            "opportunity",
            "report",
            "outreach_draft",
            "workflow_job",
        )
    for name in inserts:
        conn.exec_driver_sql(f"GRANT INSERT ON operations.{name} TO {role}")
    for name in updates:
        conn.exec_driver_sql(f"GRANT UPDATE ON operations.{name} TO {role}")


def provision(conn, org_id, name, subject, role, curator=False):
    # Directory management policies permit the migration owner to provision members.
    conn.execute(
        text("""INSERT INTO operations.organization(id,name) VALUES(:id,:n)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name"""),
        {"id": org_id, "n": name},
    )
    conn.execute(
        text("""INSERT INTO operations.membership(org_id,subject,role) VALUES(:id,:s,:r)
        ON CONFLICT(org_id,subject) DO UPDATE SET role=excluded.role"""),
        {"id": org_id, "s": subject, "r": role},
    )
    if curator:
        conn.execute(
            text("INSERT INTO operations.curator VALUES(:s) ON CONFLICT DO NOTHING"),
            {"s": subject},
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    grants = sub.add_parser("grant")
    grants.add_argument("--runtime", default="cre_runtime")
    grants.add_argument("--worker", default="cre_worker")
    org = sub.add_parser("member")
    org.add_argument("--org", type=UUID, required=True)
    org.add_argument("--name", required=True)
    org.add_argument("--subject", required=True)
    org.add_argument(
        "--role", choices=["admin", "researcher", "analyst", "viewer"], required=True
    )
    org.add_argument("--curator", action="store_true")
    sub.add_parser("demo")
    args = parser.parse_args()
    with admin_engine().begin() as conn:
        if args.command == "grant":
            if args.runtime == args.worker:
                parser.error("API and worker require distinct roles")
            grant_runtime(conn, args.runtime, False)
            grant_runtime(conn, args.worker, True)
        elif args.command == "member":
            provision(conn, args.org, args.name, args.subject, args.role, args.curator)
        else:
            from cre.auth import demo_enabled

            if not demo_enabled():
                parser.error("Enable CRE_DEMO_MODE in development before seeding")
            provision(
                conn,
                UUID("cf110000-0000-4000-a000-000000000001"),
                "Demonstration workspace",
                "local-demo-user",
                "admin",
                True,
            )


if __name__ == "__main__":
    main()
