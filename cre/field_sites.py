"""Preview and revisit organization-owned manual parcel selections."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text

from cre.auth import audit
from cre.explorer import WRITERS, Access
from cre.workflows.records import execute, one, rows

router = APIRouter(prefix="/v1/field/sites")
ACRE_M2 = 4046.8564224


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parcel_id: UUID
    geometry_version_id: UUID


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reader_version: UUID
    members: list[Member] = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def distinct_parcels(cls, members):
        distinct = {}
        for member in members:
            existing = distinct.setdefault(member.parcel_id, member)
            if existing.geometry_version_id != member.geometry_version_id:
                raise ValueError("Choose one geometry version per parcel")
        if len(distinct) > 20:
            raise ValueError("Choose up to 20 distinct parcels")
        return list(distinct.values())


class NewSite(Selection):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class SiteEdit(NewSite):
    expected_revision: int = Field(ge=1)


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def summarize_claims(parcel_ids, claims):
    """Only comparable, unambiguous observations contribute to each subtotal."""
    observations = defaultdict(list)
    for claim in claims:
        observations[(claim["parcel_id"], claim["predicate"])].append(claim)

    def trusted(parcel_id, predicate):
        group = observations[parcel_id, predicate]
        if any(
            c["verification_state"] not in ("verified", "corroborated") for c in group
        ):
            return []
        return [c["value"] for c in group]

    party_ids = set()
    unresolved = 0
    acreage = []
    assessments = defaultdict(list)
    for parcel_id in parcel_ids:
        owners = trusted(parcel_id, "recorded_owner")
        if not owners or any(not row.get("party_id") for row in owners):
            unresolved += 1
        party_ids.update(row["party_id"] for row in owners if row.get("party_id"))
        acres = {number(row.get("value")) for row in trusted(parcel_id, "deeded_acres")}
        if len(acres) == 1 and None not in acres:
            acreage.append(acres.pop())
        values = {
            (
                str(row.get("tax_year") or ""),
                str(row.get("currency") or ""),
                number(row.get("value")),
            )
            for row in trusted(parcel_id, "assessed_value")
        }
        if len(values) == 1:
            year, currency, amount = values.pop()
            if (
                len(year) == 4
                and year.isascii()
                and year.isdigit()
                and currency
                and amount is not None
            ):
                assessments[int(year), currency].append(amount)
    groups = [
        {
            "year": year,
            "currency": currency,
            "subtotal": sum(amounts),
            "covered_members": len(amounts),
        }
        for (year, currency), amounts in sorted(assessments.items())
    ]
    return {
        "source_acres": {
            "subtotal": sum(acreage) if acreage else None,
            "covered_members": len(acreage),
        },
        "ownership": {
            "known_recorded_parties": len(party_ids),
            "unresolved_members": unresolved,
        },
        "assessment_groups": groups,
        "combined_assessment": groups[0]
        if len(groups) == 1 and groups[0]["covered_members"] == len(parcel_ids)
        else None,
    }


# The version pairs, geodetic area, components and member citations come from one snapshot.
# A polygon union merges edge contacts and overlaps. Point contacts keep separate polygons.
MEASURE = """
WITH members AS MATERIALIZED (
    SELECT g.*,ref.ordinal,v.jurisdiction_id,
           (v.geometry_version_id=g.geometry_version_id AND v.reader_version=:reader) AS current_match
    FROM unnest(CAST(:parcels AS uuid[]),CAST(:versions AS uuid[])) WITH ORDINALITY
         AS ref(parcel_id,geometry_version_id,ordinal)
    JOIN core.visible_field_geometry g USING(parcel_id,geometry_version_id)
    JOIN core.visible_parcel v ON v.id=g.parcel_id
), footprint AS (
    SELECT ST_UnaryUnion(ST_Collect(geom ORDER BY ordinal)) AS geom FROM members
), components AS (
    SELECT (part).path AS path,(part).geom AS geom FROM (SELECT ST_Dump(geom) part FROM footprint) d
)
SELECT (SELECT count(*) FROM members) AS member_count,
    (SELECT count(DISTINCT jurisdiction_id) FROM members) AS jurisdictions,
    (SELECT bool_and(current_match) FROM members) AS current_match,
    (SELECT jsonb_agg(jsonb_build_object(
            'parcel_id',m.parcel_id,'geometry_version_id',m.geometry_version_id,'primary_pin',m.primary_pin,
            'observed_at',m.observed_at,'source_record_id',m.source_record_id,'run_id',m.run_id,
            'dataset_key',m.dataset_key,'publisher',m.publisher,'attribution',m.attribution,'locator',m.locator)
            ORDER BY m.ordinal)
        FROM members m) AS members,
    ST_Area(f.geom::geography) AS area_m2,ST_AsGeoJSON(f.geom)::json AS geometry,
    (SELECT jsonb_agg((SELECT jsonb_agg(m.parcel_id ORDER BY m.ordinal) FROM members m
                       WHERE ST_Relate(c.geom,m.geom,'T********')) ORDER BY c.path) FROM components c) AS components,
    (SELECT coalesce(jsonb_agg(jsonb_build_array(a.parcel_id,b.parcel_id) ORDER BY a.ordinal,b.ordinal),'[]'::jsonb)
        FROM members a JOIN members b ON a.ordinal<b.ordinal AND a.geom && b.geom
        WHERE ST_Relate(a.geom,b.geom,'F***0****')) AS point_only_contacts
FROM footprint f
"""


def measure(ctx, selection, *, historical=False):
    ids = [m.parcel_id for m in selection.members]
    result = one(
        ctx.db,
        MEASURE,
        parcels=ids,
        versions=[m.geometry_version_id for m in selection.members],
        reader=str(selection.reader_version),
    )
    current_match = result.pop("current_match")
    jurisdictions = result.pop("jurisdictions")
    if result["member_count"] != len(ids) or (not historical and not current_match):
        if historical:
            raise HTTPException(404, "Site unavailable")
        raise HTTPException(
            409, "Parcel version unavailable. Refresh your selection and preview again."
        )
    if jurisdictions != 1:
        raise HTTPException(422, "Choose parcels from one county")
    result["reader_version"] = selection.reader_version
    result["union_acres"] = result["area_m2"] / ACRE_M2
    result["disconnected"] = len(result["components"]) > 1
    return result


CLAIM_FIELDS = """c.subject_id AS parcel_id,c.id AS claim_id,c.source_record_id,c.predicate,c.value,
    c.observed_at,c.verification_state,c.dataset_key,c.publisher,c.attribution,c.locator"""


def current_claims(ctx, footprint):
    # Deeded acreage belongs to the exact geometry observation. For other facts,
    # keep all co-dated values to expose ambiguity instead of choosing an arbitrary row.
    members = footprint["members"]
    claims = rows(
        ctx.db,
        f"""WITH ranked AS (
            SELECT {CLAIM_FIELDS},dense_rank() OVER(PARTITION BY c.subject_id,c.predicate
                ORDER BY c.observed_at DESC) AS recency
            FROM unnest(CAST(:ids AS uuid[]),CAST(:sources AS uuid[])) refs(parcel,source)
            JOIN evidence.reader_parcel_claim c ON c.subject_id=refs.parcel AND c.projection_generation_id=:reader
            WHERE c.predicate IN ('assessed_value','recorded_owner')
               OR (c.predicate='deeded_acres' AND c.source_record_id=refs.source))
            SELECT * FROM ranked WHERE recency=1 ORDER BY parcel_id,predicate,claim_id,source_record_id""",
        ids=[m["parcel_id"] for m in members],
        sources=[m["source_record_id"] for m in members],
        reader=footprint["reader_version"],
    )
    if not ctx.db.scalar(
        text("""SELECT EXISTS(SELECT FROM core.visible_parcel
        WHERE id=:parcel AND projection_generation_id=:reader)"""),
        {"parcel": members[0]["parcel_id"], "reader": footprint["reader_version"]},
    ):
        raise HTTPException(409, "Reader generation changed. Refresh your selection.")
    return claims


def with_facts(footprint, claims):
    ids = [UUID(m["parcel_id"]) for m in footprint["members"]]
    return {**footprint, **summarize_claims(ids, claims), "claim_sources": claims}


@router.post("/preview")
def preview_site(body: Selection, ctx: Access):
    footprint = measure(ctx, body)
    claims = current_claims(ctx, footprint)
    return with_facts(footprint, claims)


# Deny the whole revision if a member loses either its historical geometry source
# or present parcel visibility. Never return a smaller site or a cached footprint.
AVAILABLE = """NOT EXISTS (
    SELECT FROM operations.field_site_member m
    WHERE (m.org_id,m.site_id,m.revision)=(r.org_id,r.site_id,r.revision)
      AND NOT EXISTS (SELECT FROM core.visible_field_geometry g JOIN core.visible_parcel v ON v.id=g.parcel_id
          WHERE g.parcel_id=m.parcel_id AND g.geometry_version_id=m.geometry_version_id))"""


@router.get("")
def list_sites(ctx: Access):
    return {
        "items": rows(
            ctx.db,
            f"""SELECT r.site_id AS id,r.revision,r.name,r.created_at
        FROM operations.field_site s JOIN operations.field_site_revision r
          ON (r.org_id,r.site_id,r.revision)=(s.org_id,s.id,s.current_revision)
        WHERE s.org_id=:org AND {AVAILABLE} ORDER BY r.created_at DESC,r.site_id""",
            org=ctx.org_id,
        )
    }


@router.get("/{site_id}")
def get_site(site_id: UUID, ctx: Access, revision: int | None = Query(None, ge=1)):
    meta = one(
        ctx.db,
        """SELECT r.site_id AS id,r.revision,r.name,r.created_at,r.reader_version
        FROM operations.field_site s JOIN operations.field_site_revision r
          ON (r.org_id,r.site_id,r.revision)=(s.org_id,s.id,coalesce(CAST(:rev AS int),s.current_revision))
        WHERE s.org_id=:org AND s.id=:id""",
        org=ctx.org_id,
        id=site_id,
        rev=revision,
    )
    if not meta:
        raise HTTPException(404, "Site unavailable")
    keys = {"org": ctx.org_id, "id": site_id, "rev": meta["revision"]}
    members = rows(
        ctx.db,
        """SELECT parcel_id,geometry_version_id FROM operations.field_site_member
        WHERE org_id=:org AND site_id=:id AND revision=:rev ORDER BY ordinal""",
        **keys,
    )
    footprint = measure(
        ctx,
        Selection(reader_version=meta["reader_version"], members=members),
        historical=True,
    )
    claims = rows(
        ctx.db,
        f"""SELECT {CLAIM_FIELDS} FROM operations.field_site_claim f
        JOIN evidence.visible_claim c ON (c.id,c.source_record_id,c.subject_id)=(f.claim_id,f.source_record_id,f.parcel_id)
        WHERE f.org_id=:org AND f.site_id=:id AND f.revision=:rev ORDER BY c.subject_id,c.predicate,c.id,c.source_record_id""",
        **keys,
    )
    return {**meta, **with_facts(footprint, claims)}


def persist(ctx, body, site_id=None):
    ctx.require(*WRITERS)
    org = ctx.org_id
    if site_id is None:
        site_id = ctx.db.scalar(
            text("""INSERT INTO operations.field_site(org_id,current_revision)
            VALUES(:org,1) RETURNING id"""),
            {"org": org},
        )
        revision = 1
    else:
        keys = {"org": org, "id": site_id}
        # Lock the mutable pointer first. A concurrent writer may advance it while
        # we wait; the following statement sees the winner's committed revision.
        current = ctx.db.scalar(
            text("""SELECT current_revision FROM operations.field_site
            WHERE org_id=:org AND id=:id FOR UPDATE"""),
            keys,
        )
        if current is None or not ctx.db.scalar(
            text(f"""SELECT EXISTS(
            SELECT FROM operations.field_site_revision r WHERE r.org_id=:org
            AND r.site_id=:id AND r.revision=:current AND {AVAILABLE})"""),
            {**keys, "current": current},
        ):
            raise HTTPException(404, "Site unavailable")
        if current != body.expected_revision:
            raise HTTPException(
                409, "Another edit was saved. Reopen the site before editing."
            )
        revision = current + 1
        execute(
            ctx.db,
            """UPDATE operations.field_site SET current_revision=:rev
            WHERE org_id=:org AND id=:id""",
            **keys,
            rev=revision,
        )
    footprint = measure(ctx, body)
    claims = current_claims(ctx, footprint)
    keys = {"org": org, "id": site_id, "rev": revision}
    meta = one(
        ctx.db,
        """INSERT INTO operations.field_site_revision(org_id,site_id,revision,name,reader_version,created_by)
        VALUES (:org,:id,:rev,:name,:reader,:subject) RETURNING site_id AS id,revision,name,created_at""",
        **keys,
        name=body.name,
        reader=body.reader_version,
        subject=ctx.subject,
    )
    ctx.db.execute(
        text("""INSERT INTO operations.field_site_member(org_id,site_id,revision,ordinal,parcel_id,geometry_version_id)
        VALUES (:org,:id,:rev,:ordinal,:parcel_id,:geometry_version_id)"""),
        [
            {**keys, "ordinal": ordinal, **m.model_dump()}
            for ordinal, m in enumerate(body.members, 1)
        ],
    )
    if claims:
        ctx.db.execute(
            text("""INSERT INTO operations.field_site_claim(org_id,site_id,revision,parcel_id,claim_id,source_record_id)
            VALUES (:org,:id,:rev,:parcel_id,:claim_id,:source_record_id)"""),
            [{**keys, **c} for c in claims],
        )
    audit(
        ctx,
        "field_site.save",
        site_id,
        {"revision": revision, "member_count": len(body.members)},
    )
    return {**meta, **with_facts(footprint, claims)}


@router.post("", status_code=201)
def create_site(body: NewSite, ctx: Access):
    return persist(ctx, body)


@router.put("/{site_id}")
def revise_site(site_id: UUID, body: SiteEdit, ctx: Access):
    return persist(ctx, body, site_id)
