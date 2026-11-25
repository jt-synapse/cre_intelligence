from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from cre.auth import audit
from cre.explorer import resolve_property
from cre.storage import get_bytes

from . import investigations, operations, ownership
from .contracts import Decision, ReportIn
from .operations import EDIT, Ctx, create, list_records
from .records import enqueue, execute, required
from .reports import check_entitlements, pdf_digest, snapshot
from .research import content_digest

router = APIRouter(prefix="/v1")
router.include_router(operations.router)
router.include_router(ownership.router)
router.include_router(investigations.router)


@router.post("/reports", status_code=202)
def create_report(data: ReportIn, ctx: Ctx):
    ctx.require(*EDIT)
    prop = resolve_property(ctx.db, data.property_id)
    version = snapshot(ctx.db, ctx.org_id, prop, data)
    row = create(
        ctx,
        "report",
        prop,
        dict(
            status="awaiting_review", snapshot=version, digest=content_digest(version)
        ),
        ("snapshot",),
    )
    return {k: row[k] for k in ("id", "status", "digest", "created_at")}


@router.get("/reports")
def reports(ctx: Ctx, property_id: UUID | None = None):
    ctx.require(*EDIT)
    return list_records(
        ctx,
        "report",
        property_id,
        fields="id,property_id,status,digest,created_at,reviewed_at",
    )


@router.get("/reports/{id}")
def get_report(id: UUID, ctx: Ctx):
    ctx.require(*EDIT)
    row = required(ctx.db, "report", ctx.org_id, id)
    check_entitlements(ctx.db, ctx.org_id, row["snapshot"])
    return {k: v for k, v in row.items() if k != "object_key"}


@router.post("/reports/{id}/reviews")
def review_report(id: UUID, data: Decision, ctx: Ctx):
    ctx.require(*EDIT)
    row = required(ctx.db, "report", ctx.org_id, id, lock=True)
    if row["status"] != "awaiting_review":
        raise HTTPException(409, "Report already reviewed")
    status = "rejected"
    if data.decision == "approve":
        check_entitlements(ctx.db, ctx.org_id, row["snapshot"])
        enqueue(
            ctx.db, ctx.org_id, row["property_id"], ctx.subject, "render_report", id
        )
        status = "queued"
    execute(
        ctx.db,
        """UPDATE operations.report SET status=:status,decision_reason=:reason,
        reviewer=:subject,reviewed_at=now() WHERE org_id=:org AND id=:id""",
        status=status,
        reason=data.reason,
        subject=ctx.subject,
        org=ctx.org_id,
        id=id,
    )
    audit(
        ctx, "report.reviewed", id, {"decision": data.decision, "reason": data.reason}
    )
    return {"id": id, "status": status}


@router.get("/reports/{id}/download")
def download_report(id: UUID, ctx: Ctx):
    ctx.require(*EDIT)
    row = required(ctx.db, "report", ctx.org_id, id)
    if row["status"] != "published":
        raise HTTPException(409, "Awaiting a reviewed, published report")
    check_entitlements(ctx.db, ctx.org_id, row["snapshot"])
    data = get_bytes(row["object_key"])
    if pdf_digest(data) != row["pdf_hash"]:
        raise HTTPException(503, "Stored report integrity check failed")
    audit(ctx, "report.downloaded", id)
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="dossier-{id}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/jobs")
def list_jobs(ctx: Ctx):
    ctx.require("admin")
    return list_records(
        ctx,
        "workflow_job",
        fields="id,kind,target_id,status,attempts,detail,available_at",
    )


@router.post("/jobs/{id}/retry", status_code=202)
def retry_job(id: UUID, ctx: Ctx):
    ctx.require("admin")
    job = required(ctx.db, "workflow_job", ctx.org_id, id, lock=True)
    if job["status"] != "failed":
        raise HTTPException(409, "Only exhausted jobs can be retried")
    if job["kind"] == "render_report":
        report = required(ctx.db, "report", ctx.org_id, job["target_id"], lock=True)
        check_entitlements(ctx.db, ctx.org_id, report["snapshot"])
        table = "report"
    else:
        table = "investigation"
    execute(
        ctx.db,
        f"UPDATE operations.{table} SET status='queued' WHERE id=:id AND org_id=:org",
        id=job["target_id"],
        org=ctx.org_id,
    )
    enqueue(
        ctx.db,
        ctx.org_id,
        job["property_id"],
        ctx.subject,
        job["kind"],
        job["target_id"],
    )
    audit(ctx, "job.retried", id, {"previous_attempts": job["attempts"]})
    return {"id": id, "status": "queued"}
