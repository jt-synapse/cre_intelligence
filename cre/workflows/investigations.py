from uuid import UUID

from fastapi import APIRouter, HTTPException

from cre.auth import audit
from cre.explorer import resolve_property

from .contracts import (
    Decision,
    DraftIn,
    EvidenceIn,
    FindingReview,
    InvestigationIn,
    SuppressionIn,
)
from .ownership import graph
from .operations import RESEARCH, Ctx, create, list_records, same_property
from .records import enqueue, execute, findings, one, property_claims, required, rows
from .research import channel_key, content_digest, outcome_for, quoted_channel

router = APIRouter()


@router.post("/investigations", status_code=202)
def start(data: InvestigationIn, ctx: Ctx):
    ctx.require(*RESEARCH)
    prop = resolve_property(ctx.db, data.property_id)
    row = create(
        ctx,
        "investigation",
        prop,
        dict(
            objective=data.objective,
            preferred_roles=data.preferred_roles,
            max_requests=data.max_external_requests,
            max_tokens=data.max_tokens,
        ),
        ("preferred_roles",),
    )
    enqueue(ctx.db, ctx.org_id, prop, ctx.subject, "investigate", row["id"])
    return row


@router.get("/investigations")
def cases(ctx: Ctx, property_id: UUID | None = None):
    ctx.require("admin", "researcher", "analyst")
    return list_records(
        ctx,
        "investigation",
        property_id,
        fields="id,property_id,objective,status,outcome,created_at",
    )


@router.get("/investigations/{id}")
def case(id: UUID, ctx: Ctx):
    ctx.require("admin", "researcher", "analyst")
    row = required(ctx.db, "investigation", ctx.org_id, id)
    prop = resolve_property(ctx.db, row["property_id"])
    visible = {str(c["id"]): c for c in property_claims(ctx.db, prop)}
    row["owner_evidence"] = [
        visible[str(cid)] for cid in row["owner_evidence"] if str(cid) in visible
    ]
    row["steps"] = rows(
        ctx.db,
        """SELECT name,detail,created_at FROM operations.investigation_step
        WHERE org_id=:org AND investigation_id=:id ORDER BY created_at,id""",
        org=ctx.org_id,
        id=id,
    )
    row["findings"] = findings(ctx.db, ctx.org_id, id)
    row["graph"] = graph(prop, row["findings"])
    row["reviews"] = rows(
        ctx.db,
        """SELECT r.* FROM operations.finding_review r JOIN operations.finding f
        ON f.org_id=r.org_id AND f.id=r.finding_id WHERE r.org_id=:org AND f.investigation_id=:id
        ORDER BY r.created_at,r.id""",
        org=ctx.org_id,
        id=id,
    )
    row["drafts"] = rows(
        ctx.db,
        "SELECT id,channel,body,status FROM operations.outreach_draft WHERE org_id=:org AND investigation_id=:id ORDER BY created_at,id",
        org=ctx.org_id,
        id=id,
    )
    return row


def refresh(ctx, target):
    result = outcome_for(
        findings(ctx.db, ctx.org_id, target["id"]), target["preferred_roles"]
    )
    execute(
        ctx.db,
        "UPDATE operations.investigation SET outcome=:result WHERE org_id=:org AND id=:id",
        result=result,
        org=ctx.org_id,
        id=target["id"],
    )


def validate_typing(ctx, id, subject, values):
    if values.get("identity_finding_id"):
        identity = required(
            ctx.db, "finding", ctx.org_id, values.get("identity_finding_id")
        )
        if identity["investigation_id"] != id or identity["kind"] != "entity_identity":
            raise HTTPException(
                422, "Select an entity identity finding from this investigation"
            )
        if " ".join(identity["subject"].casefold().split()) != " ".join(
            subject.casefold().split()
        ):
            raise HTTPException(
                422, "Linked identity and evidence must name the same subject"
            )
    if values.get("channel_value"):
        try:
            channel = channel_key(values.get("channel_value"))
            if (
                values.get("channel_kind") == "business_phone"
                and "@" in channel
                or values.get("channel_kind") == "business_email"
                and "@" not in channel
            ):
                raise ValueError(
                    "Business channel type does not match the supplied route"
                )
            values["channel_value"] = channel
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None


@router.post("/investigations/{id}/evidence", status_code=201)
def add_evidence(id: UUID, data: EvidenceIn, ctx: Ctx):
    ctx.require(*RESEARCH)
    target = required(ctx.db, "investigation", ctx.org_id, id, lock=True)
    values = data.model_dump()
    if data.document_id:
        doc = same_property(ctx, "document", data.document_id, target["property_id"])
        if data.exportable and not doc["exportable"]:
            raise HTTPException(422, "The document does not allow export")
    validate_typing(ctx, id, data.subject, values)
    values.update(
        investigation_id=id,
        method="authorized_manual_intake",
        source_hash=doc["sha256"]
        if data.document_id
        else content_digest(
            {k: values[k] for k in ("reference", "locator", "source_excerpt")}
        ),
    )
    finding = create(ctx, "finding", target["property_id"], values)
    refresh(ctx, target)
    return dict(finding, state="candidate")


@router.post("/investigations/{id}/reviews", status_code=201)
def review(id: UUID, data: FindingReview, ctx: Ctx):
    ctx.require(*RESEARCH)
    target = required(ctx.db, "investigation", ctx.org_id, id, lock=True)
    item = next(
        (f for f in findings(ctx.db, ctx.org_id, id) if f["id"] == data.finding_id),
        None,
    )
    if not item:
        raise HTTPException(404, "Finding unavailable")
    typed = None
    if data.enrichment:
        keys = {
            "property_role": {"relationship", "identity_finding_id"},
            "business_channel": {
                "channel_kind",
                "channel_value",
                "identity_finding_id",
            },
        }.get(item["kind"], set())
        updates = data.enrichment.model_dump(exclude_none=True)
        if not updates or not updates.keys() <= keys:
            raise HTTPException(422, "Review typing does not match this finding kind")
        typed = {k: item[k] for k in keys if item[k] is not None}
        typed.update(updates)
        validate_typing(ctx, id, item["subject"], typed)
        item.update(typed)
    if data.decision == "accept":
        if not item["document_id"] and not item["source_excerpt"]:
            raise HTTPException(
                422,
                "Verification requires a retained document or an authorized, located source excerpt",
            )
        if item["kind"] == "property_role" and not item["relationship"]:
            raise HTTPException(
                422, "A typed relationship is required to verify a property role"
            )
        if item["kind"] == "business_channel" and not (
            item["channel_kind"] and item["channel_value"]
        ):
            raise HTTPException(
                422,
                "A typed professional channel and an address or number are required",
            )
        if (
            item["kind"] == "business_channel"
            and item["method"] == "model_extraction"
            and not quoted_channel(item["channel_value"], item["source_excerpt"] or "")
        ):
            raise HTTPException(
                422,
                "The professional contact route must appear in the cited source excerpt",
            )
    version = one(
        ctx.db,
        "SELECT coalesce(max(ordinal),0)+1 AS n FROM operations.finding_review WHERE org_id=:org AND finding_id=:id",
        org=ctx.org_id,
        id=data.finding_id,
    )["n"]
    result = create(
        ctx,
        "finding_review",
        target["property_id"],
        dict(
            **data.model_dump(exclude={"enrichment"}),
            ordinal=version,
            typed_evidence=typed,
        ),
        ("typed_evidence",) if typed is not None else (),
    )
    refresh(ctx, target)
    return result


@router.post("/suppressions", status_code=201)
def suppress(data: SuppressionIn, ctx: Ctx):
    ctx.require(*RESEARCH)
    prop = resolve_property(ctx.db, data.property_id)
    try:
        channel = channel_key(data.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    existing = one(
        ctx.db,
        "SELECT * FROM operations.suppression WHERE org_id=:org AND channel=:channel",
        org=ctx.org_id,
        channel=channel,
    )
    if existing:
        return existing
    return create(ctx, "suppression", prop, dict(channel=channel, reason=data.reason))


def checked_channel(ctx, case_row, finding_id):
    items = findings(ctx.db, ctx.org_id, case_row["id"])
    candidate = next((f for f in items if f["id"] == finding_id), None)
    if (
        not candidate
        or candidate["kind"] != "business_channel"
        or candidate["state"] != "verified"
        or not candidate["channel_value"]
    ):
        raise HTTPException(422, "A reviewed professional contact route is required")
    subject_items = [
        f
        for f in items
        if f["id"] == candidate["identity_finding_id"]
        or f.get("identity_finding_id") == candidate["identity_finding_id"]
        and f["kind"] != "business_channel"
    ]
    result = outcome_for([*subject_items, candidate], case_row["preferred_roles"])
    if result not in {"verified_business_contact", "organizational_inquiry_route"}:
        raise HTTPException(
            422, "The case does not document an appropriate business route"
        )
    blocked = one(
        ctx.db,
        "SELECT id FROM operations.suppression WHERE org_id=:org AND channel=:channel",
        org=ctx.org_id,
        channel=candidate["channel_value"],
    )
    if blocked:
        raise HTTPException(409, "The business channel is suppressed")
    return candidate["channel_value"]


@router.post("/investigations/{id}/drafts", status_code=201)
def draft(id: UUID, data: DraftIn, ctx: Ctx):
    ctx.require(*RESEARCH)
    item = required(ctx.db, "investigation", ctx.org_id, id)
    channel = checked_channel(ctx, item, data.channel_finding_id)
    return create(
        ctx,
        "outreach_draft",
        item["property_id"],
        dict(investigation_id=id, channel=channel, status="draft", **data.model_dump()),
    )


@router.post("/drafts/{id}/reviews")
def approve_draft(id: UUID, data: Decision, ctx: Ctx):
    ctx.require(*RESEARCH)
    item = required(ctx.db, "outreach_draft", ctx.org_id, id, lock=True)
    if item["status"] != "draft":
        raise HTTPException(409, "Draft already reviewed")
    if data.decision == "approve":
        checked_channel(
            ctx,
            required(ctx.db, "investigation", ctx.org_id, item["investigation_id"]),
            item["channel_finding_id"],
        )
    status = "approved" if data.decision == "approve" else "rejected"
    execute(
        ctx.db,
        "UPDATE operations.outreach_draft SET status=:status,reviewer=:subject WHERE org_id=:org AND id=:id",
        status=status,
        subject=ctx.subject,
        org=ctx.org_id,
        id=id,
    )
    audit(ctx, "draft." + status, id, {"reason": data.reason})
    return required(ctx.db, "outreach_draft", ctx.org_id, id)
