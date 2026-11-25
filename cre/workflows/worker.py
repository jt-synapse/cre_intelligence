"""Tenant-scoped durable job runner. Each claim is leased before external work starts."""

import argparse
import io
import logging
import os
import time
from uuid import UUID

from cre.db import engine, tenant_scope
from cre.storage import get_bytes, put_bytes

from .records import (
    encode,
    execute,
    findings,
    insert,
    one,
    property_claims,
    required,
    rows,
    step,
)
from .reports import check_entitlements, pdf_digest, render
from .research import content_digest, extract_candidates, outcome_for, provider_name

LOG = logging.getLogger("cre.worker")
MAX_ATTEMPTS = 3


def excerpt(doc):
    raw = get_bytes(doc["object_key"])
    if doc["media_type"] in {"text/plain", "text/csv"}:
        return raw.decode("utf-8-sig")[:1800], "text:1-1800"
    if doc["media_type"] == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not len(reader.pages):
            raise ValueError("No accessible document page")
        return (reader.pages[0].extract_text() or "")[:1800], "page:1"
    return "", ""


def claim(conn, org):
    job = one(
        conn,
        """SELECT * FROM operations.workflow_job WHERE org_id=:org
        AND status IN ('queued','leased') AND available_at<=now() ORDER BY available_at,id
        FOR UPDATE SKIP LOCKED LIMIT 1""",
        org=org,
    )
    if not job:
        return None
    job = one(
        conn,
        """UPDATE operations.workflow_job SET attempts=attempts+1,status='leased',
        available_at=now()+interval '120 seconds' WHERE id=:id AND org_id=:org RETURNING *""",
        id=job["id"],
        org=org,
    )
    job["token_budget"] = 0
    job["meter"] = {}
    if job["kind"] == "investigate":
        case = required(conn, "investigation", org, job["target_id"], lock=True)
        if (
            provider_name() != "disabled"
            and case["requests_used"] < case["max_requests"]
            and case["tokens_used"] < case["max_tokens"]
        ):
            eligible = one(
                conn,
                """SELECT id FROM operations.document WHERE org_id=:org AND
                core.current_property_id(property_id)=core.current_property_id(:prop) AND allow_ai AND property_id IS NOT NULL
                AND media_type IN ('application/pdf','text/plain','text/csv') LIMIT 1""",
                org=org,
                prop=case["property_id"],
            )
            if eligible:
                job["token_budget"] = min(
                    8000, case["max_tokens"] - case["tokens_used"]
                )
                step(
                    conn,
                    case,
                    "reserve_provider_request",
                    {
                        "provider": provider_name(),
                        "model": os.getenv("CRE_OPENAI_MODEL")
                        if provider_name() == "openai"
                        else None,
                        "tokens_reserved": job["token_budget"],
                        "attempt": job["attempts"],
                    },
                )
        execute(
            conn,
            """UPDATE operations.investigation SET status='running',
            requests_used=requests_used+:requests,tokens_used=tokens_used+:tokens WHERE id=:id AND org_id=:org""",
            requests=int(bool(job["token_budget"])),
            tokens=job["token_budget"],
            id=case["id"],
            org=org,
        )
    return job


def investigate(conn, job):
    org = job["org_id"]
    case = required(conn, "investigation", org, job["target_id"], lock=True)
    prop = one(
        conn, "SELECT core.current_property_id(:id) AS id", id=case["property_id"]
    )["id"]
    owner = [
        c["id"]
        for c in property_claims(conn, prop)
        if c["predicate"]
        in {"assessor_listed_owner", "recorded_title", "recorded_grantee"}
    ]
    step(
        conn,
        case,
        "query_ownership",
        {"source": "eligible property claims", "observations": len(owner)},
    )
    docs = rows(
        conn,
        """SELECT * FROM operations.document WHERE org_id=:org
        AND core.current_property_id(property_id)=:prop ORDER BY created_at DESC,id LIMIT 100""",
        org=org,
        prop=prop,
    )
    step(
        conn,
        case,
        "inspect_authorized_documents",
        {"documents": len(docs), "remote_registry": "manual intake"},
    )
    limitation = "Registry and deed coverage is limited to authorized evidence supplied to this case."
    if job["token_budget"]:
        excerpts = []
        by_id = {}
        for doc in docs:
            if not doc["allow_ai"] or len(excerpts) >= 8:
                continue
            try:
                value, locator = excerpt(doc)
            except Exception as exc:
                step(
                    conn,
                    case,
                    "document_unavailable",
                    {"document_id": str(doc["id"]), "reason": type(exc).__name__},
                )
                continue
            if value.strip():
                excerpts.append(
                    {"document_id": str(doc["id"]), "text": value, "locator": locator}
                )
                by_id[doc["id"]] = (doc, locator)
        candidates, used = extract_candidates(
            excerpts, job["token_budget"], job["id"], job["meter"]
        )
        for item in candidates:
            doc, locator = by_id[item.document_id]
            insert(
                conn,
                "finding",
                dict(
                    org_id=org,
                    property_id=prop,
                    created_by="worker",
                    investigation_id=case["id"],
                    kind=item.kind,
                    subject=item.subject,
                    assertion=item.assertion,
                    reference=doc["name"],
                    locator=locator,
                    document_id=doc["id"],
                    exportable=doc["exportable"],
                    method="model_extraction",
                    source_hash=doc["sha256"],
                    source_excerpt=item.quote,
                ),
            )
        execute(
            conn,
            "UPDATE operations.investigation SET tokens_used=tokens_used-:unused WHERE org_id=:org AND id=:id",
            unused=job["token_budget"] - used,
            org=org,
            id=case["id"],
        )
        step(
            conn,
            case,
            "extract_candidates",
            {
                "accepted_candidates": len(candidates),
                "provider": provider_name(),
                "tokens_used": used,
                **job["meter"],
            },
        )
    elif case["requests_used"]:
        limitation += " The configured research budget is exhausted; review previous provider attempts."
    result = outcome_for(findings(conn, org, case["id"]), case["preferred_roles"])
    step(conn, case, "evaluate_evidence", {"outcome": result})
    execute(
        conn,
        """UPDATE operations.investigation SET status='completed',outcome=:outcome,limitation=:lim,
        owner_evidence=cast(:owners as jsonb) WHERE id=:id AND org_id=:org""",
        org=org,
        id=case["id"],
        owners=encode(owner),
        outcome=result,
        lim=limitation,
    )


def render_report(conn, job):
    row = required(conn, "report", job["org_id"], job["target_id"], lock=True)
    if (
        not row["reviewer"]
        or row["status"] != "queued"
        or content_digest(row["snapshot"]) != row["digest"]
    ):
        raise ValueError("Report review or snapshot invalid")
    check_entitlements(conn, job["org_id"], row["snapshot"])
    payload = render(row["snapshot"])
    execute(
        conn,
        """UPDATE operations.report SET status='published',object_key=:key,pdf_hash=:hash
        WHERE org_id=:org AND id=:id""",
        org=job["org_id"],
        id=row["id"],
        key=put_bytes(payload),
        hash=pdf_digest(payload),
    )


def run_once(org_id):
    org_id = UUID(str(org_id))
    with engine().begin() as conn:
        tenant_scope(conn, org_id)
        job = claim(conn, org_id)
    if not job:
        return False
    with engine().begin() as conn:
        tenant_scope(conn, org_id)
        current = required(conn, "workflow_job", org_id, job["id"], lock=True)
        if current["status"] != "leased" or current["attempts"] != job["attempts"]:
            return True
        try:
            with conn.begin_nested():
                (investigate if job["kind"] == "investigate" else render_report)(
                    conn, job
                )
            execute(
                conn,
                "UPDATE operations.workflow_job SET status='completed' WHERE id=:id AND org_id=:org",
                org=org_id,
                id=job["id"],
            )
        except Exception as exc:
            reason = type(exc).__name__
            dead = job["attempts"] >= MAX_ATTEMPTS
            LOG.warning(
                "workflow job %s attempt %d failed (%s)",
                job["id"],
                job["attempts"],
                reason,
            )
            execute(
                conn,
                """UPDATE operations.workflow_job SET status=:status,detail=:reason,
                available_at=now()+:delay*interval '1 second' WHERE id=:id AND org_id=:org""",
                org=org_id,
                id=job["id"],
                status="failed" if dead else "queued",
                reason=reason,
                delay=2 ** job["attempts"],
            )
            if job["kind"] == "investigate":
                case = required(conn, "investigation", org_id, job["target_id"])
                if "total_tokens" in job["meter"]:
                    execute(
                        conn,
                        "UPDATE operations.investigation SET tokens_used=tokens_used-:unused WHERE org_id=:org AND id=:id",
                        unused=job["token_budget"] - job["meter"]["total_tokens"],
                        org=org_id,
                        id=case["id"],
                    )
                step(
                    conn,
                    case,
                    "attempt_failed",
                    {
                        "attempt": job["attempts"],
                        "reason": reason,
                        **job["meter"],
                        "http_status": getattr(
                            getattr(exc, "response", None), "status_code", None
                        ),
                    },
                )
            if dead:
                table = "investigation" if job["kind"] == "investigate" else "report"
                execute(
                    conn,
                    f"UPDATE operations.{table} SET status='failed' WHERE id=:id AND org_id=:org",
                    org=org_id,
                    id=job["target_id"],
                )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=UUID)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        if args.org:
            orgs = [args.org]
        else:
            with engine().connect() as conn:
                orgs = [
                    r["id"]
                    for r in rows(
                        conn, "SELECT id FROM operations.organization ORDER BY id"
                    )
                ]
        count = sum(run_once(org) for org in orgs)
        if args.once:
            return
        if not count:
            time.sleep(1)


if __name__ == "__main__":
    main()
