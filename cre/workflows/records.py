"""Scoped queries shared by the HTTP and worker processes."""

import json

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text


def rows(conn, query, **args):
    return [dict(item) for item in conn.execute(text(query), args).mappings()]


def one(conn, query, **args):
    found = conn.execute(text(query), args).mappings().first()
    return dict(found) if found is not None else None


def execute(conn, query, **args):
    return conn.execute(text(query), args)


def required(conn, table, org, id, *, lock=False):
    result = one(
        conn,
        f"SELECT * FROM operations.{table} WHERE org_id=:org AND id=:id"
        + (" FOR UPDATE" if lock else ""),
        org=org,
        id=id,
    )
    if not result:
        raise HTTPException(404, "Record unavailable")
    return result


def encode(value):
    return json.dumps(value, default=str, ensure_ascii=False, allow_nan=False)


def insert(conn, table, values, json_fields=()):
    keys = list(values)
    binds = [f"cast(:{k} as jsonb)" if k in json_fields else f":{k}" for k in keys]
    return one(
        conn,
        f"INSERT INTO operations.{table} ({','.join(keys)}) VALUES ({','.join(binds)}) RETURNING *",
        **{k: encode(v) if k in json_fields else v for k, v in values.items()},
    )


def findings(conn, org, case):
    result = rows(
        conn,
        """SELECT f.*, (SELECT h.typed_evidence FROM operations.finding_review h
        WHERE h.org_id=f.org_id AND h.finding_id=f.id AND h.typed_evidence IS NOT NULL
        ORDER BY h.ordinal DESC LIMIT 1) AS reviewed_typing, r.reason AS review_reason, r.ordinal AS review_version,
        r.decision AS decision, coalesce((SELECT h.correction FROM operations.finding_review h WHERE h.org_id=f.org_id AND h.finding_id=f.id AND h.decision='correct' ORDER BY h.ordinal DESC LIMIT 1),f.assertion) AS current_assertion,
        CASE r.decision WHEN 'accept' THEN 'verified' WHEN 'correct' THEN 'candidate'
            WHEN 'conflict' THEN 'conflicted' WHEN 'stale' THEN 'stale'
            WHEN 'reject' THEN 'rejected' ELSE 'candidate' END AS state,
        r.id AS review_id FROM operations.finding f
        LEFT JOIN LATERAL (SELECT * FROM operations.finding_review
           WHERE org_id=f.org_id AND finding_id=f.id ORDER BY ordinal DESC LIMIT 1) r ON true
        WHERE f.org_id=:org AND f.investigation_id=:case ORDER BY f.created_at, f.id""",
        org=org,
        case=case,
    )

    for item in result:
        typing = item.pop("reviewed_typing")
        if typing:
            item.update(typing)
            if item.get("identity_finding_id"):
                item["identity_finding_id"] = UUID(str(item["identity_finding_id"]))
    return result


def property_claims(conn, prop, export_only=False):
    return rows(
        conn,
        """SELECT DISTINCT c.id,c.subject_id,c.subject_type,c.predicate,c.value,
            c.verification_state,c.observed_at,c.source_record_id,c.locator,c.dataset_key,c.export_allowed,
            c.publisher,c.source_origin,c.attribution,c.content_sha256,c.run_id
        FROM evidence.visible_claim c WHERE ((c.subject_type='property'
        AND core.current_property_id(c.subject_id)=:prop) OR
        (c.subject_type='parcel' AND c.subject_id IN (
            SELECT parcel_id FROM core.property_parcel WHERE valid_to IS NULL
            AND core.current_property_id(property_id)=:prop)))
        AND (:all_visible OR c.export_allowed) ORDER BY c.id""",
        prop=prop,
        all_visible=not export_only,
    )


def enqueue(conn, org, prop, actor, kind, target):
    execute(
        conn,
        """INSERT INTO operations.workflow_job (org_id,property_id,created_by,kind,target_id)
        VALUES (:org,:prop,:actor,:kind,:target)
        ON CONFLICT (org_id,kind,target_id) DO UPDATE SET
        status='queued',attempts=0,available_at=now(),detail=NULL""",
        org=org,
        prop=prop,
        actor=actor,
        kind=kind,
        target=target,
    )


def step(conn, case, name, detail):
    return insert(
        conn,
        "investigation_step",
        dict(
            org_id=case["org_id"],
            property_id=case["property_id"],
            created_by="worker",
            investigation_id=case["id"],
            name=name,
            detail=detail,
        ),
        ("detail",),
    )
