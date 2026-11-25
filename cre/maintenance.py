"""Operational status and read-only verification for an isolated restored environment."""

import argparse
import json
from collections import Counter
from hashlib import sha256

from sqlalchemy import text

from cre.admin import admin_engine
from cre.storage import get_bytes


def health(conn):
    # Operator-only connection. Never expose per-tenant counts through a public health route.
    queries = {
        "sources": """SELECT d.dataset_key,d.enabled,d.shared_display,a.status,a.completed_at,a.observed_on,
          coalesce(a.quality,r.metrics) AS metrics FROM provenance.source_dataset d LEFT JOIN LATERAL
          (SELECT status,completed_at,observed_on,run_id,quality FROM provenance.ingestion_attempt
           WHERE dataset_id=d.id ORDER BY started_at DESC LIMIT 1) a ON true
          LEFT JOIN provenance.ingestion_run r ON a.run_id=r.id ORDER BY d.dataset_key""",
        "jobs": """SELECT kind,status,count(*) AS jobs,min(created_at) AS oldest_created_at,
          min(available_at) AS earliest_available_at FROM operations.workflow_job GROUP BY kind,status""",
        "research": """SELECT id,status,outcome,requests_used,tokens_used FROM operations.investigation
          ORDER BY created_at DESC LIMIT 100""",
        "usage": """SELECT investigation_id,detail FROM operations.investigation_step
          WHERE name IN ('extract_candidates','attempt_failed') AND detail ? 'total_tokens' ORDER BY created_at DESC LIMIT 100""",
    }
    return {
        name: [dict(r) for r in conn.execute(text(q)).mappings()]
        for name, q in queries.items()
    }


def verify_restore(conn):
    from cre.workflows.reports import render

    counters = Counter()
    # Including failed/quarantined retained inputs catches holes in storage backups.
    keys = conn.execute(
        text("""SELECT raw_object_key FROM provenance.ingestion_attempt WHERE raw_object_key IS NOT NULL
      UNION SELECT raw_object_key FROM provenance.ingestion_run
      UNION SELECT object_key FROM core.screening_layer
      UNION SELECT object_key FROM operations.document
      UNION SELECT object_key FROM operations.report WHERE object_key IS NOT NULL""")
    ).scalars()
    for key in keys:
        get_bytes(key)
        counters["objects_verified"] += 1
    for snapshot, expected in conn.execute(
        text("SELECT snapshot,pdf_hash FROM operations.report WHERE status='published'")
    ):
        if sha256(render(snapshot)).hexdigest() != expected:
            raise RuntimeError(
                "A restored report could not be reconstructed from its pinned inputs"
            )
        counters["reports_reconstructed"] += 1
    for name, query in {
        "unsupported_claims": "SELECT count(*) FROM evidence.claim c WHERE NOT EXISTS(SELECT 1 FROM evidence.claim_support s WHERE s.claim_id=c.id)",
        "invalid_geometries": "SELECT count(*) FROM core.parcel_geometry_version WHERE is_current AND NOT ST_IsValid(geom)",
    }.items():
        counters[name] = conn.scalar(text(query))
        if counters[name]:
            raise RuntimeError(f"Restore verification failed for {name}")
    return dict(counters)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["health", "verify-restore"])
    args = parser.parse_args()
    with admin_engine().begin() as conn:
        conn.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        # Fail instead of reporting a misleading success if the credential cannot inspect all tenants.
        conn.exec_driver_sql("SET LOCAL row_security=off")
        data = (health if args.command == "health" else verify_restore)(conn)
        print(json.dumps(data, default=str, indent=2))


if __name__ == "__main__":
    main()
