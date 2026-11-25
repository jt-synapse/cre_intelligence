import hashlib
from pathlib import PurePath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from cre.auth import Context, audit, context
from cre.explorer import resolve_property
from cre.storage import get_bytes, put_bytes

from .contracts import ActivityIn, OpportunityIn, OpportunityPatch, ScenarioIn
from .finance import MODEL_VERSION, calculate
from .records import execute, insert, required, rows

router = APIRouter()
Ctx = Annotated[Context, Depends(context, scope="function")]
EDIT = ("admin", "researcher", "analyst")
RESEARCH = ("admin", "researcher")
MAX_FILE = 8 * 1024 * 1024


def base(ctx, prop):
    return {"org_id": ctx.org_id, "property_id": prop, "created_by": ctx.subject}


def create(ctx, table, prop, values, json_fields=()):
    result = insert(ctx.db, table, {**base(ctx, prop), **values}, json_fields)
    audit(ctx, table + ".created", result["id"])
    return result


def list_records(ctx, table, prop=None, limit=100, fields="*"):
    clause = ""
    args = {"org": ctx.org_id, "limit": limit}
    if prop is not None:
        args["prop"] = resolve_property(ctx.db, prop)
        clause = "AND core.current_property_id(property_id)=:prop"
    return rows(
        ctx.db,
        f"""SELECT {fields} FROM operations.{table}
                WHERE org_id=:org {clause} ORDER BY created_at DESC,id LIMIT :limit""",
        **args,
    )


def same_property(ctx, table, id, prop):
    record = required(ctx.db, table, ctx.org_id, id)
    if resolve_property(ctx.db, record["property_id"]) != resolve_property(
        ctx.db, prop
    ):
        raise HTTPException(422, "Record belongs to a different property")
    return record


@router.post("/opportunities", status_code=201)
def create_opportunity(data: OpportunityIn, ctx: Ctx):
    ctx.require(*EDIT)
    prop = resolve_property(ctx.db, data.property_id)
    return create(ctx, "opportunity", prop, data.model_dump(exclude={"property_id"}))


@router.get("/opportunities")
def opportunities(ctx: Ctx, property_id: UUID | None = None):
    return list_records(ctx, "opportunity", property_id)


@router.get("/opportunities/{id}")
def opportunity(id: UUID, ctx: Ctx):
    result = required(ctx.db, "opportunity", ctx.org_id, id)
    result["activities"] = rows(
        ctx.db,
        """SELECT * FROM operations.activity WHERE org_id=:org
        AND opportunity_id=:id ORDER BY created_at,id""",
        org=ctx.org_id,
        id=id,
    )
    return result


@router.patch("/opportunities/{id}")
def patch_opportunity(id: UUID, data: OpportunityPatch, ctx: Ctx):
    ctx.require(*EDIT)
    previous = required(ctx.db, "opportunity", ctx.org_id, id, lock=True)
    if "stage" in data.model_fields_set and data.stage is None:
        raise HTTPException(422, "A stage is required")
    values = data.model_dump(exclude_unset=True)
    if values:
        execute(
            ctx.db,
            f"UPDATE operations.opportunity SET {','.join(k + '=:' + k for k in values)} WHERE org_id=:org AND id=:id",
            org=ctx.org_id,
            id=id,
            **values,
        )
        audit(
            ctx,
            "opportunity.updated",
            id,
            {"previous": {k: previous[k] for k in values}, "changes": values},
        )
        create(
            ctx,
            "activity",
            previous["property_id"],
            dict(
                opportunity_id=id,
                kind="change",
                body=", ".join(f"{k}: {previous[k]} → {v}" for k, v in values.items()),
            ),
        )
    return opportunity(id, ctx)


@router.post("/opportunities/{id}/activities", status_code=201)
def add_activity(id: UUID, data: ActivityIn, ctx: Ctx):
    ctx.require(*EDIT)
    prop = required(ctx.db, "opportunity", ctx.org_id, id)["property_id"]
    if data.document_id:
        same_property(ctx, "document", data.document_id, prop)
    return create(ctx, "activity", prop, dict(opportunity_id=id, **data.model_dump()))


@router.post("/analysis-scenarios", status_code=201)
def scenario(data: ScenarioIn, ctx: Ctx):
    ctx.require("admin", "analyst")
    prop = resolve_property(ctx.db, data.property_id)
    values = data.model_dump(mode="json", exclude={"property_id"})
    if set(data.sources) - set(values["inputs"]):
        raise HTTPException(422, "A source must identify a scenario input")
    values.update(outputs=calculate(data.inputs), model_version=MODEL_VERSION)
    return create(
        ctx, "analysis_scenario", prop, values, ("inputs", "outputs", "sources")
    )


@router.get("/analysis-scenarios")
def scenarios(ctx: Ctx, property_id: UUID | None = None):
    return list_records(ctx, "analysis_scenario", property_id)


@router.get("/analysis-scenarios/{id}")
def get_scenario(id: UUID, ctx: Ctx):
    return required(ctx.db, "analysis_scenario", ctx.org_id, id)


def metadata(document):
    return {key: value for key, value in document.items() if key != "object_key"}


@router.post("/documents", status_code=201)
def upload(
    ctx: Ctx,
    property_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    kind: Annotated[
        Literal["deed", "filing", "rent_roll", "lease", "research", "other"], Form()
    ] = "other",
    exportable: Annotated[bool, Form()] = False,
    allow_ai: Annotated[bool, Form()] = False,
    supersedes_id: Annotated[UUID | None, Form()] = None,
):
    ctx.require(*EDIT)
    prop = resolve_property(ctx.db, property_id)
    if supersedes_id:
        same_property(ctx, "document", supersedes_id, prop)
    raw = file.file.read(MAX_FILE + 1)
    if not raw or len(raw) > MAX_FILE:
        raise HTTPException(413, "Document must contain between 1 byte and 8 MiB")
    filename = PurePath((file.filename or "document").replace("\\", "/")).name[:180]
    suffix = PurePath(filename).suffix.lower()
    media = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(suffix)
    if (
        not media
        or suffix == ".pdf"
        and not raw.startswith(b"%PDF-")
        or suffix == ".xlsx"
        and not raw.startswith(b"PK")
    ):
        raise HTTPException(
            422, "Upload a PDF, TXT, CSV, or XLSX document of the declared type"
        )
    if suffix in {".txt", ".csv"}:
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Text document must use UTF-8") from None
    record = create(
        ctx,
        "document",
        prop,
        dict(
            name=filename,
            kind=kind,
            media_type=media,
            object_key=put_bytes(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw),
            exportable=exportable,
            allow_ai=allow_ai,
            supersedes_id=supersedes_id,
        ),
    )
    return metadata(record)


@router.get("/documents")
def documents(ctx: Ctx, property_id: UUID | None = None):
    ctx.require(*EDIT)
    return [metadata(d) for d in list_records(ctx, "document", property_id)]


@router.get("/documents/{id}/download")
def download(id: UUID, ctx: Ctx):
    ctx.require(*EDIT)
    doc = required(ctx.db, "document", ctx.org_id, id)
    raw = get_bytes(doc["object_key"])
    if hashlib.sha256(raw).hexdigest() != doc["sha256"]:
        raise HTTPException(503, "Stored document integrity check failed")
    audit(ctx, "document.accessed", id)
    return Response(
        raw,
        media_type=doc["media_type"],
        headers={
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/documents/{id}/restrict")
def restrict(id: UUID, ctx: Ctx):
    ctx.require("admin")
    required(ctx.db, "document", ctx.org_id, id, lock=True)
    execute(
        ctx.db,
        "UPDATE operations.document SET exportable=false,allow_ai=false WHERE org_id=:org AND id=:id",
        org=ctx.org_id,
        id=id,
    )
    audit(ctx, "document.restricted", id)
    return metadata(required(ctx.db, "document", ctx.org_id, id))
