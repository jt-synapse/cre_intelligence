"""Canonical property read model and explicit, audited workspace saves."""

import math
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from cre.auth import Context, audit, bind_subject, context, identify, memberships
from cre.db import engine
from cre.ingestion.contract import normalize_pin

router = APIRouter(prefix="/v1")
Access = Annotated[Context, Depends(context, scope="function")]
WRITERS = ("admin", "analyst", "researcher")


def rows(conn, query, **params):
    return [dict(row) for row in conn.execute(text(query), params).mappings()]


@router.get("/me")
def me(subject: Annotated[str, Depends(identify)]):
    with engine().begin() as conn:
        bind_subject(conn, subject)
        return {
            "subject": subject,
            "organizations": memberships(conn, subject),
            "can_curate": bool(
                conn.scalar(text("SELECT EXISTS(SELECT 1 FROM operations.curator)"))
            ),
        }


# Resolve against currently entitled geometry for reads, saves, investigations and exports.
VISIBLE_PROPERTIES = """SELECT DISTINCT p.id,p.name,p.asset_class,p.property_status
 FROM core.property p JOIN core.property_parcel pp ON p.id=pp.property_id AND pp.valid_to IS NULL
 JOIN core.visible_parcel vp ON vp.id=pp.parcel_id WHERE p.property_status <> 'superseded'"""


def resolve_property(conn: Connection, property_id: str | UUID) -> UUID:
    result = conn.scalar(
        text(
            f"SELECT id FROM ({VISIBLE_PROPERTIES}) p WHERE id=core.current_property_id(:id)"
        ),
        {"id": property_id},
    )
    if result is None:
        raise HTTPException(404, "Property unavailable")
    return result


SUMMARY_COLUMNS = """v.id,v.primary_pin,v.address,v.county_fips,v.observed_at,v.dataset_key,v.source_record_id,v.publisher,v.source_origin,v.attribution,v.run_id,
 v.geometry_version_id,v.projection_generation_id,v.reader_version,
 CASE WHEN cardinality(links.ids)=1 THEN links.ids[1] END AS property_id,
 CASE WHEN cardinality(links.ids)=1 THEN links.states[1] END AS property_status,
 links.ids AS property_candidates"""
PARCEL_COLUMNS = SUMMARY_COLUMNS + ", ST_AsGeoJSON(v.geom)::json AS geometry"
PARCEL_FROM = """FROM core.visible_parcel v LEFT JOIN LATERAL (
 SELECT array_agg(p.id ORDER BY p.id) ids,array_agg(p.property_status ORDER BY p.id) states
 FROM core.property_parcel pp JOIN core.property p ON p.id=pp.property_id
 WHERE pp.parcel_id=v.id AND pp.valid_to IS NULL AND p.property_status <> 'superseded') links ON true"""


def coordinate_list(value: str, count: int):
    try:
        vals = [float(n) for n in value.split(",")]
        if len(vals) != count or not all(math.isfinite(n) for n in vals):
            raise ValueError
        if any(abs(n) > (180 if i % 2 == 0 else 90) for i, n in enumerate(vals)):
            raise ValueError
        if count == 4 and (vals[0] >= vals[2] or vals[1] >= vals[3]):
            raise ValueError
        return vals
    except ValueError:
        raise HTTPException(
            422, "Use longitude,latitude coordinates in WGS84"
        ) from None


@router.get("/parcels")
def parcels(
    ctx: Access,
    q: str = Query("", max_length=200),
    county_fips: str | None = Query(None, pattern=r"^\d{5}$"),
    bbox: str | None = None,
    point: str | None = None,
    limit: int = Query(150, ge=1, le=1000),
):
    conditions, params = [], {"limit": limit}
    if county_fips:
        conditions.append("v.county_fips=:county")
        params["county"] = county_fips
    if q.strip():
        conditions.append("""(v.normalized_pin=:pin OR (:pin <> '' AND starts_with(v.normalized_pin,:pin))
          OR lower(v.address) LIKE lower(:pattern) ESCAPE '#' OR v.primary_pin=:q
          OR EXISTS (SELECT 1 FROM evidence.reader_owner o WHERE o.subject_id=v.id
            AND lower(o.value->>'value') LIKE lower(:pattern) ESCAPE '#'))""")
        term = q.strip()
        pattern = (
            "%" + term.replace("#", "##").replace("%", "#%").replace("_", "#_") + "%"
        )
        params.update(q=term, pin=normalize_pin(term), pattern=pattern)
    if bbox:
        coords = coordinate_list(bbox, 4)
        params.update(zip(("w", "s", "e", "n"), coords))
        conditions.append("ST_Intersects(v.geom,ST_MakeEnvelope(:w,:s,:e,:n,4326))")
    if point:
        params["lon"], params["lat"] = coordinate_list(point, 2)
        conditions.append("ST_Covers(v.geom,ST_SetSRID(ST_MakePoint(:lon,:lat),4326))")
    where = " AND ".join(conditions) or "true"
    result = rows(
        ctx.db,
        f"SELECT {PARCEL_COLUMNS} {PARCEL_FROM} WHERE {where} ORDER BY v.primary_pin,v.id LIMIT :limit",
        **params,
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r.pop("id"),
                "geometry": r.pop("geometry"),
                "properties": r,
            }
            for r in result
        ],
    }


def screening(conn, parcel_id):
    return rows(
        conn,
        """SELECT l.dataset_key,l.kind,l.reference,l.observed_on,
       CASE WHEN f.id IS NOT NULL THEN 'intersection' ELSE 'screened_no_match' END AS result,
       f.label,f.locator FROM core.visible_parcel v CROSS JOIN core.visible_screening_layer l
       LEFT JOIN core.visible_screening_feature f ON f.layer_id=l.id AND ST_Intersects(f.geom,v.geom)
       WHERE v.id=:id AND (f.id IS NOT NULL OR ST_Covers(l.coverage,v.geom)) ORDER BY l.kind,f.locator""",
        id=parcel_id,
    )


def parcel_detail(conn, parcel_id, generation=None, summary=False):
    columns = SUMMARY_COLUMNS if summary else PARCEL_COLUMNS
    result = rows(conn, f"SELECT {columns} {PARCEL_FROM} WHERE v.id=:id", id=parcel_id)
    if not result:
        raise HTTPException(404, "Parcel unavailable")
    parcel = result[0]
    if generation and parcel["projection_generation_id"] != generation:
        raise HTTPException(
            409, "The parcel map has been refreshed. Select the parcel again."
        )
    parcel["owners"] = rows(
        conn,
        """SELECT value->>'value' AS name,dataset_key,observed_at,verification_state,
        (array_agg(source_record_id ORDER BY source_record_id))[1] AS source_record_id,
        array_agg(source_record_id ORDER BY source_record_id) AS source_record_ids
        FROM evidence.reader_owner WHERE subject_id=:id
        GROUP BY coalesce(value->>'party_id',id::text),value->>'value',dataset_key,observed_at,verification_state
        ORDER BY name,source_record_id""",
        id=parcel_id,
    )
    parcel["map_destination"] = conn.scalar(
        text("""
        SELECT ST_AsGeoJSON(ST_PointOnSurface(geom))::json FROM core.visible_parcel
        WHERE id=:id AND projection_generation_id=:gen
    """),
        {"id": parcel_id, "gen": parcel["projection_generation_id"]},
    )
    if summary:
        return parcel
    parcel["claims"] = rows(
        conn,
        """SELECT * FROM evidence.reader_parcel_claim WHERE subject_type='parcel'
        AND subject_id=:id ORDER BY observed_at DESC,predicate,id""",
        id=parcel_id,
    )
    parcel["screening"] = screening(conn, parcel_id)
    return parcel


@router.get("/parcels/{parcel_id}")
def get_parcel(
    parcel_id: UUID, ctx: Access, generation: UUID | None = None, summary: bool = False
):
    return parcel_detail(ctx.db, parcel_id, generation, summary)


@router.get("/tiles/{generation}/{z}/{x}/{y}")
def parcel_tile(generation: UUID, z: int, x: int, y: int, ctx: Access):
    if not 0 <= z <= 22 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise HTTPException(422, "Invalid tile coordinates")
    tile = ctx.db.scalar(
        text("""
        WITH bounds AS (SELECT ST_TileEnvelope(:z,:x,:y) AS box),
        tile_rows AS (
          SELECT v.id::text AS parcel_id,v.primary_pin,v.address,
          ST_AsMVTGeom(ST_Transform(v.geom,3857),b.box,4096,64,true) AS geom
          FROM core.visible_parcel v CROSS JOIN bounds b
          WHERE v.projection_generation_id=:gen
          AND v.geom && ST_Transform(ST_Expand(b.box,(ST_XMax(b.box)-ST_XMin(b.box))/64),4326))
        SELECT ST_AsMVT(tile_rows,'parcels',4096,'geom') FROM tile_rows WHERE geom IS NOT NULL
        """),
        {"gen": generation, "z": z, "x": x, "y": y},
    )
    return Response(bytes(tile or b""), media_type="application/vnd.mapbox-vector-tile")


@router.get("/properties")
def properties(
    ctx: Access,
    q: str = Query("", max_length=200),
    limit: int = Query(100, ge=1, le=500),
):
    return {
        "items": rows(
            ctx.db,
            f"""SELECT p.id,coalesce(p.name,min(v.address),min(v.primary_pin)) AS name,
        p.property_status,p.asset_class FROM ({VISIBLE_PROPERTIES}) p JOIN core.property_parcel pp
        ON pp.property_id=p.id AND pp.valid_to IS NULL JOIN core.visible_parcel v ON pp.parcel_id=v.id
        WHERE strpos(lower(concat_ws(' ',p.name,v.address,v.primary_pin)),lower(:q))>0 OR :q=''
        GROUP BY p.id,p.name,p.property_status,p.asset_class ORDER BY name,p.id LIMIT :limit""",
            q=q.strip(),
            limit=limit,
        )
    }


@router.get("/properties/{property_id}")
def get_property(property_id: UUID, ctx: Access):
    pid = resolve_property(ctx.db, property_id)
    item = rows(
        ctx.db,
        "SELECT id,name,asset_class,property_status FROM core.property WHERE id=:id",
        id=pid,
    )[0]
    parcel_ids = rows(
        ctx.db,
        """SELECT DISTINCT v.id FROM core.property_parcel pp JOIN core.visible_parcel v
        ON v.id=pp.parcel_id WHERE pp.property_id=:id AND pp.valid_to IS NULL ORDER BY v.id""",
        id=pid,
    )
    item["parcels"] = [parcel_detail(ctx.db, p["id"]) for p in parcel_ids]
    first = item["parcels"][0]
    item["name"] = item["name"] or first["address"] or first["primary_pin"]
    return item


class Save(BaseModel):
    parcel_id: UUID
    property_id: UUID | None = None


def lock_identity(conn):
    # Serialize the rare create/merge operations; searches and unrelated workflow writes continue.
    conn.execute(text("SELECT pg_advisory_xact_lock(71722,2)"))


@router.post("/workspace/saves")
def save(body: Save, ctx: Access):
    ctx.require(*WRITERS)
    lock_identity(ctx.db)
    visible = rows(
        ctx.db, f"SELECT links.ids {PARCEL_FROM} WHERE v.id=:id", id=body.parcel_id
    )
    if not visible:
        raise HTTPException(404, "Parcel unavailable")
    candidates = visible[0]["ids"] or []
    if body.property_id:
        pid = resolve_property(ctx.db, body.property_id)
        if pid not in candidates:
            raise HTTPException(409, "Property is not linked to this parcel")
    elif len(candidates) > 1:
        raise HTTPException(
            409,
            {
                "message": "Choose a linked property",
                "candidates": [str(i) for i in candidates],
            },
        )
    elif candidates:
        pid = candidates[0]
    else:
        pid = ctx.db.scalar(
            text(
                "INSERT INTO core.property(property_status) VALUES('provisional') RETURNING id"
            )
        )
        ctx.db.execute(
            text("""INSERT INTO core.property_parcel(property_id,parcel_id,valid_from)
            VALUES(:pid,:parcel,CURRENT_DATE)"""),
            {"pid": pid, "parcel": body.parcel_id},
        )
    ctx.db.execute(
        text("""INSERT INTO operations.saved_property(org_id,property_id,subject)
       VALUES(:org,:pid,:sub) ON CONFLICT DO NOTHING"""),
        {"org": ctx.org_id, "pid": pid, "sub": ctx.subject},
    )
    audit(ctx, "workspace.save", pid)
    status = ctx.db.scalar(
        text("SELECT property_status FROM core.property WHERE id=:id"), {"id": pid}
    )
    return {"property_id": pid, "property_status": status}


@router.get("/workspace/saves")
def saves(ctx: Access):
    return {
        "items": rows(
            ctx.db,
            f"""SELECT p.id AS property_id,coalesce(p.name,min(v.address),min(v.primary_pin)) AS name,
        p.property_status FROM ({VISIBLE_PROPERTIES}) p JOIN operations.saved_property s
        ON core.current_property_id(s.property_id)=p.id JOIN core.property_parcel pp ON pp.property_id=p.id
        AND pp.valid_to IS NULL JOIN core.visible_parcel v ON pp.parcel_id=v.id
        GROUP BY p.id,p.name,p.property_status ORDER BY name,p.id""",
        )
    }


class Group(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    merge_property_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/properties/{property_id}/grouping")
def group(property_id: UUID, body: Group, ctx: Access):
    ctx.require("admin", "researcher")
    if not ctx.db.scalar(text("SELECT EXISTS(SELECT 1 FROM operations.curator)")):
        raise HTTPException(403, "Shared property curator privilege required")
    lock_identity(ctx.db)
    target = resolve_property(ctx.db, property_id)
    others = {resolve_property(ctx.db, old) for old in body.merge_property_ids} - {
        target
    }
    for old in sorted(others):
        ctx.db.execute(
            text("""INSERT INTO core.property_parcel(property_id,parcel_id,relationship_type,valid_from)
          SELECT :target,pp.parcel_id,pp.relationship_type,CURRENT_DATE FROM core.property_parcel pp
          WHERE pp.property_id=:old AND pp.valid_to IS NULL AND NOT EXISTS(SELECT 1 FROM core.property_parcel e
          WHERE e.property_id=:target AND e.parcel_id=pp.parcel_id AND e.relationship_type=pp.relationship_type AND e.valid_to IS NULL)"""),
            {"old": old, "target": target},
        )
        ctx.db.execute(
            text(
                "UPDATE core.property_parcel SET valid_to=CURRENT_DATE WHERE property_id=:id AND valid_to IS NULL"
            ),
            {"id": old},
        )
        ctx.db.execute(
            text("UPDATE core.property SET property_status='superseded' WHERE id=:id"),
            {"id": old},
        )
        ctx.db.execute(
            text(
                "INSERT INTO core.property_alias(old_id,current_id) VALUES(:old,:target)"
            ),
            {"old": old, "target": target},
        )
    ctx.db.execute(
        text(
            "UPDATE core.property SET name=:n,property_status='confirmed' WHERE id=:id"
        ),
        {"n": body.name, "id": target},
    )
    audit(
        ctx,
        "property.group",
        target,
        {"merged": list(map(str, others)), "reason": body.reason},
    )
    return get_property(target, ctx)


class Portfolio(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/portfolios", status_code=201)
def create_portfolio(body: Portfolio, ctx: Access):
    ctx.require(*WRITERS)
    key = ctx.db.scalar(
        text("""INSERT INTO operations.portfolio(org_id,name) VALUES(:org,:name)
        ON CONFLICT(org_id,name) DO UPDATE SET name=excluded.name RETURNING id"""),
        {"org": ctx.org_id, "name": body.name},
    )
    audit(ctx, "portfolio.create", key)
    return {"id": key, "name": body.name}


@router.get("/portfolios")
def portfolios(ctx: Access):
    return {
        "items": rows(
            ctx.db,
            f"""SELECT pf.id,pf.name,coalesce(array_agg(DISTINCT p.id)
       FILTER(WHERE p.id IS NOT NULL),'{{}}') AS property_ids FROM operations.portfolio pf
       LEFT JOIN operations.portfolio_property pp ON pp.portfolio_id=pf.id
       LEFT JOIN ({VISIBLE_PROPERTIES}) p ON p.id=core.current_property_id(pp.property_id)
       GROUP BY pf.id ORDER BY pf.name""",
        )
    }


@router.put("/portfolios/{portfolio_id}/properties/{property_id}")
def add_to_portfolio(portfolio_id: UUID, property_id: UUID, ctx: Access):
    ctx.require(*WRITERS)
    pid = resolve_property(ctx.db, property_id)
    if not ctx.db.scalar(
        text("SELECT id FROM operations.portfolio WHERE id=:id"), {"id": portfolio_id}
    ):
        raise HTTPException(404, "Portfolio unavailable")
    ctx.db.execute(
        text("""INSERT INTO operations.portfolio_property(org_id,portfolio_id,property_id)
        VALUES(:org,:pf,:p) ON CONFLICT DO NOTHING"""),
        {"org": ctx.org_id, "pf": portfolio_id, "p": pid},
    )
    audit(ctx, "portfolio.add", portfolio_id, {"property_id": str(pid)})
    return {"portfolio_id": portfolio_id, "property_id": pid}


class ClaimDecision(BaseModel):
    decision: Literal[
        "verified", "corroborated", "candidate", "conflicted", "stale", "unresolved"
    ]
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/claims/{claim_id}/reviews", status_code=201)
def review_claim(claim_id: UUID, body: ClaimDecision, ctx: Access):
    ctx.require("admin", "researcher")
    if not ctx.db.scalar(text("SELECT EXISTS(SELECT 1 FROM operations.curator)")):
        raise HTTPException(403, "Shared evidence curator privilege required")
    if not ctx.db.scalar(
        text("SELECT EXISTS(SELECT 1 FROM evidence.visible_claim WHERE id=:id)"),
        {"id": claim_id},
    ):
        raise HTTPException(404, "Claim unavailable")
    ctx.db.execute(
        text("""INSERT INTO evidence.claim_review_event(claim_id,reviewer,decision,reason)
        VALUES(:id,:subject,:decision,:reason)"""),
        {"id": claim_id, "subject": ctx.subject, **body.model_dump()},
    )
    audit(ctx, "claim.review", claim_id, body.model_dump())
    return {"claim_id": claim_id, "decision": body.decision}


@router.get("/parcels/{parcel_id}/related")
def related_parcels(
    parcel_id: UUID,
    ctx: Access,
    generation: UUID,
    mode: Literal["party", "mailing", "control"] = "party",
):
    parcel_detail(ctx.db, parcel_id, generation, summary=True)
    # Each result retains both ends of the relationship. Name similarity and agent
    # addresses are never sufficient to establish party identity or control.
    owner_observations = """
        SELECT subject_id,value->>'party_id' AS key,source_record_id,dataset_key
        FROM evidence.reader_owner WHERE verification_state IN ('verified','corroborated')
    """
    if mode == "mailing":
        observations = """
          SELECT subject_id,lower(trim(value->>'value')) AS key,source_record_id,dataset_key
          FROM (SELECT c.*,dense_rank() OVER (PARTITION BY subject_id,dataset_key
                ORDER BY observed_at DESC) AS rank
                FROM evidence.reader_parcel_claim c WHERE predicate='mailing_address') ranked
          WHERE rank=1 AND verification_state NOT IN ('conflicted','stale')
        """
    else:
        observations = owner_observations
    relation = "JOIN obs b ON a.key=b.key"
    extra_sources = ""
    if mode == "control":
        relation = """JOIN evidence.reader_control ca ON ca.controlled::text=a.key
                      JOIN evidence.reader_control cb ON ca.controller=cb.controller
                      JOIN obs b ON cb.controlled::text=b.key"""
        extra_sources = ",ca.source_record_id AS control_source,cb.source_record_id AS related_control_source"
    matches = rows(
        ctx.db,
        f"""
        WITH obs AS ({observations}), pairs AS (
          SELECT DISTINCT ON (b.subject_id) b.subject_id,a.source_record_id AS selected_source,
             b.source_record_id AS related_source,b.dataset_key {extra_sources}
          FROM obs a {relation} WHERE a.subject_id=:id AND b.subject_id<>a.subject_id
          AND a.key IS NOT NULL AND a.key<>'' ORDER BY b.subject_id,a.source_record_id,b.source_record_id)
        SELECT {PARCEL_COLUMNS},pairs.selected_source,pairs.related_source,
        pairs.dataset_key AS relationship_source {",pairs.control_source,pairs.related_control_source" if mode == "control" else ""}
        {PARCEL_FROM} JOIN pairs ON pairs.subject_id=v.id
        WHERE v.projection_generation_id=:generation ORDER BY v.primary_pin,v.id LIMIT 100
        """,
        id=parcel_id,
        generation=generation,
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r.pop("id"),
                "geometry": r.pop("geometry"),
                "properties": r,
            }
            for r in matches
        ],
    }
