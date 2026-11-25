"""Evidence-qualified ownership and relationship read models for the Explorer."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from cre.explorer import resolve_property

from .operations import Ctx, EDIT
from .records import findings, one, property_claims, rows

router = APIRouter()
OWNER_PREDICATES = {
    "assessor_listed_owner",
    "recorded_title",
    "recorded_grantee",
    "recorded_owner",
}


def graph(property_id, items):
    """Only explicitly linked identities produce edges. Each edge points to its own finding."""
    identities = {
        f["id"]: f
        for f in items
        if f["kind"] == "entity_identity" and f["state"] == "verified"
    }
    nodes = {property_id: {"id": property_id, "kind": "property"}}
    for key, identity in identities.items():
        nodes[key] = {
            "id": key,
            "kind": "entity_identity",
            "name": identity["subject"],
            "state": identity["state"],
        }
    edges = []
    for item in items:
        identity = item["identity_finding_id"]
        if item["state"] != "verified" or identity not in identities:
            continue
        if item["kind"] == "property_role":
            source, target, kind = identity, property_id, item["relationship"]
        elif item["kind"] == "business_channel":
            source, target, kind = identity, item["id"], item["channel_kind"]
            nodes[target] = {
                "id": target,
                "kind": "business_channel",
                "value": item["channel_value"],
                "state": item["state"],
            }
        else:
            continue
        if kind:
            edges.append(
                {
                    "from": source,
                    "to": target,
                    "relationship": kind,
                    "state": item["state"],
                    "finding_id": item["id"],
                    "reference": item["reference"],
                    "locator": item["locator"],
                    "observed_at": item["created_at"],
                    "effective_date": item["effective_date"],
                }
            )
    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/properties/{id}/ownership")
def property_ownership(id: UUID, ctx: Ctx):
    prop = resolve_property(ctx.db, id)
    return {
        "property_id": prop,
        "claims": [
            c
            for c in property_claims(ctx.db, prop)
            if c["predicate"] in OWNER_PREDICATES
        ],
    }


@router.get("/entities/{id}")
def entity(id: UUID, ctx: Ctx):
    shared = rows(
        ctx.db,
        """SELECT value->>'value' AS name,id AS claim_id,subject_id AS parcel_id,source_record_id,locator,
            observed_at,verification_state,source_origin,publisher,dataset_key FROM evidence.visible_claim
            WHERE value->>'party_id'=:key AND predicate='assessor_listed_owner' ORDER BY observed_at DESC,id""",
        key=str(id),
    )
    if shared:
        return {
            "id": id,
            "kind": "assessor_listed_party",
            "name": shared[0]["name"],
            "references": shared,
        }
    ctx.require(*EDIT)
    identity = one(
        ctx.db,
        """SELECT * FROM operations.finding WHERE org_id=:org AND id=:id AND kind='entity_identity'""",
        org=ctx.org_id,
        id=id,
    )
    if not identity:
        raise HTTPException(404, "Entity unavailable")
    item = next(
        f
        for f in findings(ctx.db, ctx.org_id, identity["investigation_id"])
        if f["id"] == id
    )
    if item["state"] != "verified":
        raise HTTPException(404, "Entity unavailable")
    return {
        "id": id,
        "kind": "investigated_entity",
        "name": item["subject"],
        "references": [item],
    }


@router.get("/entities/{id}/relationships")
def relationships(id: UUID, ctx: Ctx):
    result = entity(id, ctx)
    if result["kind"] == "assessor_listed_party":
        return {
            "entity_id": id,
            "relationships": [
                {
                    "from": id,
                    "to": s["parcel_id"],
                    "relationship": "assessor_listed_owner",
                    "state": s["verification_state"],
                    "source_record_id": s["source_record_id"],
                    "locator": s["locator"],
                }
                for s in result["references"]
            ],
        }
    identity = result["references"][0]
    case_items = findings(ctx.db, ctx.org_id, identity["investigation_id"])
    edges = graph(identity["property_id"], case_items)["edges"]
    return {
        "entity_id": id,
        "relationships": [e for e in edges if e["from"] == id or e["to"] == id],
    }
