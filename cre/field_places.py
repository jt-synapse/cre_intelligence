"""Online workspace folders, labeled parcel pins, and recorded field visits."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from cre.auth import audit
from cre.explorer import WRITERS, Access
from cre.field_capture import require_parcel
from cre.workflows.records import one, rows

router = APIRouter(prefix="/v1/field/places")


class Folder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    color: Literal["teal", "blue", "amber", "violet", "rose", "slate"]


class Pin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    folder_id: UUID | None = None


class Visit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID


@router.get("")
def places(ctx: Access):
    folders = rows(
        ctx.db,
        """SELECT id,name,color FROM operations.field_folder
        WHERE org_id=:org ORDER BY lower(name),id""",
        org=ctx.org_id,
    )
    pins = rows(
        ctx.db,
        """SELECT p.parcel_id,p.label,p.folder_id,v.primary_pin,
        ST_AsGeoJSON(ST_PointOnSurface(v.geom))::json->'coordinates' AS point,
        (SELECT max(h.visited_at) FROM operations.field_visit h
         WHERE h.org_id=p.org_id AND h.parcel_id=p.parcel_id) AS last_visited_at
        FROM operations.field_pin p JOIN core.visible_parcel v ON v.id=p.parcel_id
        WHERE p.org_id=:org ORDER BY lower(p.label),p.parcel_id""",
        org=ctx.org_id,
    )
    return {"folders": folders, "pins": pins}


@router.post("/folders")
def create_folder(body: Folder, ctx: Access):
    ctx.require(*WRITERS)
    params = {"org": ctx.org_id, **body.model_dump()}
    folder = one(
        ctx.db,
        """INSERT INTO operations.field_folder(org_id,name,color)
        VALUES(:org,:name,:color) ON CONFLICT DO NOTHING RETURNING id,name,color""",
        **params,
    )
    if folder:
        audit(ctx, "field_folder.create", folder["id"])
        return folder
    existing = one(
        ctx.db,
        """SELECT id,name,color FROM operations.field_folder
        WHERE org_id=:org AND lower(name)=lower(:name)""",
        **params,
    )
    if not existing or existing["color"] != body.color:
        raise HTTPException(409, "A folder with this name already uses another color")
    return existing


@router.put("/parcels/{parcel_id}/pin")
def save_pin(parcel_id: UUID, body: Pin, ctx: Access):
    ctx.require(*WRITERS)
    require_parcel(ctx, parcel_id)
    if body.folder_id and not one(
        ctx.db,
        """SELECT id FROM operations.field_folder
        WHERE org_id=:org AND id=:id""",
        org=ctx.org_id,
        id=body.folder_id,
    ):
        raise HTTPException(404, "Folder unavailable")
    pin = one(
        ctx.db,
        """INSERT INTO operations.field_pin(org_id,parcel_id,label,folder_id)
        VALUES(:org,:parcel,:label,:folder_id) ON CONFLICT(org_id,parcel_id)
        DO UPDATE SET label=excluded.label,folder_id=excluded.folder_id
        RETURNING parcel_id,label,folder_id""",
        org=ctx.org_id,
        parcel=parcel_id,
        **body.model_dump(),
    )
    audit(ctx, "field_pin.save", parcel_id)
    return pin


VISIT_FIELDS = "parcel_id,created_by,visited_at"


@router.get("/parcels/{parcel_id}/visits")
def recent_visits(parcel_id: UUID, ctx: Access):
    require_parcel(ctx, parcel_id)
    return {
        "items": rows(
            ctx.db,
            f"""SELECT {VISIT_FIELDS} FROM operations.field_visit
        WHERE org_id=:org AND parcel_id=:parcel ORDER BY visited_at DESC,operation_id DESC LIMIT 20""",
            org=ctx.org_id,
            parcel=parcel_id,
        )
    }


@router.post("/parcels/{parcel_id}/visits")
def record_visit(parcel_id: UUID, body: Visit, ctx: Access):
    ctx.require(*WRITERS)
    require_parcel(ctx, parcel_id)
    params = {
        "org": ctx.org_id,
        "actor": ctx.subject,
        "op": body.operation_id,
        "parcel": parcel_id,
    }
    visit = one(
        ctx.db,
        f"""INSERT INTO operations.field_visit(org_id,created_by,operation_id,parcel_id)
        VALUES(:org,:actor,:op,:parcel) ON CONFLICT DO NOTHING RETURNING {VISIT_FIELDS}""",
        **params,
    )
    if visit:
        audit(
            ctx,
            "field_visit.record",
            parcel_id,
            {"operation_id": str(body.operation_id)},
        )
        return visit
    previous = one(
        ctx.db,
        f"""SELECT {VISIT_FIELDS} FROM operations.field_visit
        WHERE org_id=:org AND created_by=:actor AND operation_id=:op AND parcel_id=:parcel""",
        **params,
    )
    if not previous:
        raise HTTPException(409, "Visit operation already used")
    return previous
