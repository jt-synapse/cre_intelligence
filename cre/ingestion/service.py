"""Source registration, atomic publication, and auditable operator import attempts."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date
from hashlib import file_digest, sha256

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from cre import storage
from cre.db import engine

from .contract import (
    PRIVATE_GWINNETT_DATASETS,
    Manifest,
    SnapshotError,
    normalize_pin,
    parse_snapshot,
)


def sql(conn, query, **params):
    return conn.execute(text(query), params)


@contextmanager
def private_import_diagnostics():
    """COPY and parser errors may include source rows. Keep CLI diagnostics aggregate."""
    try:
        yield
    except PermissionError:
        raise PermissionError(
            "Private Gwinnett access denied. Use scripts/gwinnett-internal with "
            "the approved source policy and private local database."
        ) from None
    except Exception as exc:  # noqa: BLE001 -- parser and driver errors can contain private source rows.
        raise RuntimeError(
            f"Private Gwinnett import failed ({type(exc).__name__}). "
            "Check the private source files and scripts/gwinnett-internal health."
        ) from None


def register(manifest: Manifest, *, only_if_missing: bool = False):
    """Operator-only control plane. Re-registering updates visibility for past records."""
    config = manifest.model_dump_json()
    with engine().begin() as conn:
        # Serialize initial provisioning with later operator edits to the same contract.
        sql(
            conn,
            "SELECT pg_advisory_xact_lock(hashtextextended(:key,71))",
            key=manifest.dataset_key,
        )
        if only_if_missing:
            existing = sql(
                conn,
                "SELECT id FROM provenance.source_dataset WHERE dataset_key=:key",
                key=manifest.dataset_key,
            ).scalar_one_or_none()
            if existing:
                return str(existing)
        source_id = sql(
            conn,
            """INSERT INTO provenance.source_system(source_key,publisher)
            VALUES (:key,:publisher) ON CONFLICT(source_key) DO UPDATE SET publisher=excluded.publisher
            RETURNING id""",
            key=manifest.source_key,
            publisher=manifest.publisher,
        ).scalar_one()
        previous = sql(
            conn,
            """SELECT manifest FROM provenance.source_dataset
            WHERE dataset_key=:key FOR UPDATE""",
            key=manifest.dataset_key,
        ).scalar_one_or_none()
        if previous:
            old = Manifest.model_validate(previous)
            if (old.source_key, old.county_fips, old.kind) != (
                manifest.source_key,
                manifest.county_fips,
                manifest.kind,
            ):
                raise ValueError(
                    "dataset namespace, jurisdiction and kind are immutable"
                )
            mapping_fields = (
                "columns",
                "known_columns",
                "worksheets",
                "workbook_patterns",
                "archive_companions",
                "join_identifier",
                "join_dataset",
            )
            if old.mapping_version == manifest.mapping_version and any(
                getattr(old, k) != getattr(manifest, k) for k in mapping_fields
            ):
                raise ValueError("changed mapping requires a new mapping_version")
        ds = sql(
            conn,
            """INSERT INTO provenance.source_dataset
            (source_system_id,dataset_key,manifest,enabled,shared_display,export_allowed)
            VALUES (:source_id,:key,CAST(:config AS jsonb),:enabled,:display,:export)
            ON CONFLICT(dataset_key) DO UPDATE SET manifest=excluded.manifest,enabled=excluded.enabled,
            shared_display=excluded.shared_display,export_allowed=excluded.export_allowed RETURNING id""",
            source_id=source_id,
            key=manifest.dataset_key,
            config=config,
            enabled=manifest.rights.status == "approved",
            display=manifest.rights.shared_display,
            export=manifest.rights.export_allowed,
        ).scalar_one()
        if previous != manifest.model_dump(mode="json"):
            sql(
                conn,
                """INSERT INTO provenance.manifest_event(dataset_id,manifest)
                VALUES (:ds,CAST(:config AS jsonb))""",
                ds=ds,
                config=config,
            )
        if (
            previous
            and manifest.rights.shared_display
            and manifest.rights.status == "approved"
            and (not old.rights.shared_display or old.rights.status != "approved")
        ):
            runs = (
                sql(
                    conn,
                    """SELECT id FROM provenance.ingestion_run WHERE dataset_id=:ds
                ORDER BY observed_on,published_at,id""",
                    ds=ds,
                )
                .scalars()
                .all()
            )
            for run in runs:
                sql(conn, "SELECT core.advance_parcel_reader(:run)", run=run)
    return str(ds)


def _dataset(conn, key, *, lock=False):
    clause = " FOR SHARE" if lock else ""
    row = (
        sql(
            conn,
            "SELECT id,manifest FROM provenance.source_dataset WHERE dataset_key=:key"
            + clause,
            key=key,
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"unknown dataset {key}; register its reviewed manifest first")
    return row["id"], Manifest.model_validate(row["manifest"])


def _review(conn, attempt_id, reason, record=None, locator=None):
    sql(
        conn,
        """INSERT INTO staging.review_item(attempt_id,source_record_id,reason,locator)
        VALUES (:attempt,:record,:reason,CAST(:locator AS jsonb))""",
        attempt=attempt_id,
        record=record,
        reason=reason,
        locator=json.dumps(locator or {}),
    )


def _finish(conn, attempt, status, detail=None, run=None, quality=None):
    sql(
        conn,
        """UPDATE provenance.ingestion_attempt SET status=:status,detail=:detail,
        completed_at=clock_timestamp(),run_id=:run,quality=CAST(:quality AS jsonb) WHERE id=:id""",
        id=attempt,
        status=status,
        detail=detail,
        quality=json.dumps(quality) if quality is not None else None,
        run=run,
    )


def import_snapshot(
    key: str,
    data: bytes | Callable[[], bytes],
    observed: date,
    method: str = "manual",
    *,
    reconcile: bool = False,
) -> dict:
    # Authorization precedes writing any artifact or derived source record.
    with engine().begin() as conn:
        ds_id, manifest = _dataset(conn, key)
        attempt = sql(
            conn,
            """INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on)
            VALUES (:ds,:method,'acquiring',:observed) RETURNING id""",
            ds=ds_id,
            method=method,
            observed=observed,
        ).scalar_one()
    try:
        manifest.authorize(method)
        if key in PRIVATE_GWINNETT_DATASETS:
            raise PermissionError(
                "Use scripts/gwinnett-internal import for the private Gwinnett evaluation"
            )
        # Hold a shared lock on the policy through storage to serialize revocations.
        with engine().begin() as conn:
            _, current = _dataset(conn, key, lock=True)
            current.authorize(method)
            if current != manifest:
                raise SnapshotError(
                    "source manifest changed; retry with its current version"
                )
            data = data() if callable(data) else data
            digest = sha256(data).hexdigest()
            artifact = storage.put_bytes(data)
            sql(
                conn,
                """UPDATE provenance.ingestion_attempt SET raw_object_key=:obj,
                artifact_sha256=:digest,status='staging' WHERE id=:id""",
                id=attempt,
                obj=artifact,
                digest=digest,
            )
        rows = parse_snapshot(manifest, data)
        if not rows:
            raise SnapshotError("empty snapshot requires review")
        if (
            manifest.expected_snapshot_rows is not None
            and len(rows) != manifest.expected_snapshot_rows
        ):
            raise SnapshotError(
                "Full snapshot row count differs from the declared coverage"
            )
        fingerprint = sha256(
            "".join(sorted(r.digest() for r in rows)).encode()
        ).hexdigest()
        if manifest.reader_release:
            fingerprint = sha256(
                (fingerprint + ":" + manifest.reader_release).encode()
            ).hexdigest()
        with engine().begin() as conn:
            _, current = _dataset(conn, key, lock=True)
            current.authorize(method)
            if current != manifest:
                raise SnapshotError(
                    "source manifest changed; retry with its current version"
                )
            # One county publishes at a time, including independent assessor and GIS snapshots.
            sql(
                conn,
                "SELECT pg_advisory_xact_lock(174274, :county)",
                county=int(manifest.county_fips),
            )
            existing = (
                sql(
                    conn,
                    """SELECT id,metrics,observed_on,raw_object_key FROM provenance.ingestion_run
                WHERE dataset_id=:ds AND input_fingerprint=:fp AND mapping_version=:version
                  AND observed_on=:observed""",
                    ds=ds_id,
                    fp=fingerprint,
                    version=manifest.mapping_version,
                    observed=observed,
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                quality = existing["metrics"]
                status = "replayed" if quality["accepted"] else "quarantined"
                if reconcile and manifest.kind == "assessor" and quality["unmatched"]:
                    # A replayed attempt can have a differently ordered artifact. Source
                    # locators always point to the original published artifact.
                    if existing["raw_object_key"] != artifact:
                        rows = parse_snapshot(
                            manifest, storage.get_bytes(existing["raw_object_key"])
                        )
                    quality, recovered = _recover_unmatched(
                        conn, manifest, ds_id, attempt, existing, rows
                    )
                    if recovered:
                        status = "reconciled"
                        if manifest.rights.shared_display:
                            sql(
                                conn,
                                "SELECT core.advance_parcel_reader(:run,true)",
                                run=existing["id"],
                            )
                _finish(conn, attempt, status, run=existing["id"], quality=quality)
                return {
                    "attempt_id": str(attempt),
                    "run_id": str(existing["id"]),
                    "status": status,
                    **quality,
                }
            return _publish(
                conn,
                manifest,
                ds_id,
                attempt,
                rows,
                observed,
                fingerprint,
                artifact,
                digest,
            )
    except Exception as exc:
        status = (
            "blocked"
            if isinstance(exc, PermissionError)
            else "quarantined"
            if isinstance(exc, SnapshotError)
            else "failed"
        )
        with engine().begin() as conn:
            _finish(conn, attempt, status, str(exc)[:2000])
            if status == "quarantined":
                _review(conn, attempt, str(exc)[:2000])
        raise


def _publish(
    conn, manifest, ds, attempt, rows, observed, fingerprint, artifact, digest
):
    prior = sql(
        conn,
        """SELECT id FROM provenance.ingestion_run WHERE dataset_id=:ds
        AND observed_on<=:date ORDER BY observed_on DESC,published_at DESC LIMIT 1""",
        ds=ds,
        date=observed,
    ).scalar()
    metrics = dict(
        read=len(rows),
        accepted=0,
        quarantined=0,
        unmatched=0,
        changed=0,
        conflicting=0,
        new_parcels=0,
        missing_from_snapshot=0,
        usable_addresses=0,
        matched_owners=0,
    )
    if prior:
        old = set(
            sql(
                conn,
                "SELECT external_record_id FROM provenance.source_record WHERE run_id=:run",
                run=prior,
            ).scalars()
        )
        metrics["missing_from_snapshot"] = len(old - {r.external_id for r in rows})
    run = sql(
        conn,
        """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,
        manifest,observed_on,raw_object_key,artifact_sha256,metrics)
        VALUES (:ds,:fp,:mv,CAST(:cfg AS jsonb),:day,:obj,:sha,'{}') RETURNING id""",
        ds=ds,
        fp=fingerprint,
        mv=manifest.mapping_version,
        cfg=manifest.model_dump_json(),
        day=observed,
        obj=artifact,
        sha=digest,
    ).scalar_one()
    jurisdiction = sql(
        conn,
        """INSERT INTO core.jurisdiction(county_fips,county_name,state_code)
        VALUES (:fips,:name,:state) ON CONFLICT(county_fips) DO UPDATE SET county_name=excluded.county_name
        RETURNING id""",
        fips=manifest.county_fips,
        name=manifest.county_name,
        state=manifest.state_code,
    ).scalar_one()
    duplicates = Counter(normalize_pin(r.fields.get("pin") or "") for r in rows)
    identifiers = Counter(
        (k, str(r.fields[k]).strip().upper())
        for r in rows
        for k in ("global_id", "taxpin", "lrsn")
        if r.fields.get(k) is not None
    )
    for row in rows:
        record = sql(
            conn,
            """INSERT INTO provenance.source_record(run_id,external_record_id,content_sha256,locator)
            VALUES (:run,:external,:hash,CAST(:locator AS jsonb)) RETURNING id""",
            run=run,
            external=row.external_id,
            hash=row.digest(),
            locator=json.dumps(row.locator),
        ).scalar_one()
        try:
            if row.error:
                raise Reject(row.error)
            if manifest.kind == "parcels" and (
                duplicates[normalize_pin(row.fields["pin"])] > 1
                or any(
                    identifiers[(k, str(row.fields[k]).strip().upper())] > 1
                    for k in ("global_id", "taxpin", "lrsn")
                    if row.fields.get(k) is not None
                )
            ):
                raise Reject("colliding source identifiers", "conflicting")
            with conn.begin_nested():
                if manifest.kind == "parcels":
                    deltas = _parcel(
                        conn, ds, jurisdiction, manifest, record, row, observed
                    )
                else:
                    deltas = _assessor(
                        conn, ds, jurisdiction, manifest, record, row, observed, attempt
                    )
            for metric, count in deltas.items():
                metrics[metric] += count
            metrics["accepted"] += 1
        except Reject as exc:
            _review(conn, attempt, str(exc), record, row.locator)
            metrics["quarantined"] += 1
            if exc.metric:
                metrics[exc.metric] += 1
    sql(
        conn,
        "UPDATE provenance.ingestion_run SET metrics=CAST(:metrics AS jsonb) WHERE id=:run",
        metrics=json.dumps(metrics),
        run=run,
    )
    status = "published" if metrics["accepted"] else "quarantined"
    if status == "published" and manifest.rights.shared_display:
        sql(conn, "SELECT core.advance_parcel_reader(:run)", run=run)
    _finish(conn, attempt, status, run=run, quality=metrics)
    return {
        "attempt_id": str(attempt),
        "run_id": str(run),
        "status": status,
        **metrics,
    }


class Reject(ValueError):
    def __init__(self, reason, metric=None):
        super().__init__(reason)
        self.metric = metric


def _resolve(conn, ds, jurisdiction, fields):
    current = sql(
        conn,
        """SELECT id FROM core.parcel WHERE jurisdiction_id=:j
        AND normalized_pin=:pin AND parcel_state='active'""",
        j=jurisdiction,
        pin=normalize_pin(fields["pin"]),
    ).scalar()
    candidates = {current} if current else set()
    for field in ("global_id", "taxpin", "lrsn"):
        if fields.get(field) is None:
            continue
        rows = sql(
            conn,
            """SELECT i.parcel_id FROM core.parcel_identifier i JOIN core.parcel p ON p.id=i.parcel_id
            WHERE i.dataset_id=:ds AND i.identifier_type=:type AND i.normalized_value=:value AND i.is_current
            AND p.jurisdiction_id=:j AND p.parcel_state='active'""",
            ds=ds,
            type=field,
            value=str(fields[field]).strip().upper(),
            j=jurisdiction,
        )
        candidates.update(rows.scalars())
    if len(candidates) > 1:
        raise Reject("source mapping and parcel identifiers disagree", "conflicting")
    return next(iter(candidates), None)


def _geometry(conn, row):
    geometry = row.geometry
    if not isinstance(geometry, dict) or geometry.get("type") not in (
        "Polygon",
        "MultiPolygon",
    ):
        raise Reject("missing polygon or unsupported geometry type")
    try:
        with conn.begin_nested():
            result = (
                sql(
                    conn,
                    """WITH shape AS (
                SELECT ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:json),:srid),4326)) geom)
                SELECT ST_AsEWKB(geom) AS wkb, ST_IsValidReason(geom) AS reason,
                  (ST_IsValid(geom) AND NOT ST_IsEmpty(geom) AND ST_NDims(geom)=2 AND
                   ST_CoveredBy(geom,ST_MakeEnvelope(-180,-90,180,90,4326))) AS valid FROM shape""",
                    json=json.dumps(geometry),
                    srid=row.srid,
                )
                .mappings()
                .one()
            )
    except DBAPIError as exc:
        state = getattr(exc.orig, "sqlstate", "") or ""
        if state == "XX000" or state.startswith("22"):
            raise Reject(
                "invalid geometry encoding or coordinate transformation"
            ) from exc
        raise
    if not result["valid"]:
        raise Reject(f"invalid or out-of-range geometry: {result['reason']}")
    return bytes(result["wkb"])


def _claim(
    conn, pid, predicate, value, record, row, manifest, field, day, state="verified"
):
    claim = sql(
        conn,
        """INSERT INTO evidence.claim(subject_type,subject_id,predicate,value,
        verification_state,observed_at,extraction_method) VALUES
        ('parcel',:pid,:pred,CAST(:val AS jsonb),:state,CAST(:day AS date)::timestamp AT TIME ZONE 'UTC','direct_mapping') RETURNING id""",
        pid=pid,
        pred=predicate,
        val=json.dumps(value),
        state=state,
        day=day,
    ).scalar_one()
    locator = {**row.locator, "field": manifest.columns[field]}
    sql(
        conn,
        """INSERT INTO evidence.claim_support(claim_id,source_record_id,locator)
        VALUES(:claim,:record,CAST(:loc AS jsonb))""",
        claim=claim,
        record=record,
        loc=json.dumps(locator),
    )
    return claim


def _parcel(conn, ds, jurisdiction, manifest, record, row, day):
    f = row.fields
    wkb = _geometry(conn, row)
    pid = _resolve(conn, ds, jurisdiction, f)
    new = pid is None
    normalized = normalize_pin(f["pin"])
    if new:
        pid = sql(
            conn,
            """INSERT INTO core.parcel(jurisdiction_id,primary_pin,normalized_pin)
            VALUES(:j,:pin,:norm) RETURNING id""",
            j=jurisdiction,
            pin=f["pin"],
            norm=normalized,
        ).scalar_one()
    latest = sql(
        conn,
        """SELECT max(last_seen) FROM core.parcel_identifier WHERE parcel_id=:pid""",
        pid=pid,
    ).scalar()
    is_latest = latest is None or day >= latest
    if is_latest and not new:
        sql(
            conn,
            "UPDATE core.parcel SET primary_pin=:pin,normalized_pin=:norm WHERE id=:pid",
            pid=pid,
            pin=f["pin"],
            norm=normalized,
        )
    for key in ("pin", "taxpin", "lrsn", "global_id"):
        if f.get(key) is None:
            continue
        raw = str(f[key])
        norm = normalized if key == "pin" else raw.strip().upper()
        if is_latest:
            sql(
                conn,
                """UPDATE core.parcel_identifier SET is_current=false WHERE parcel_id=:pid AND
                dataset_id=:ds AND identifier_type=:key AND normalized_value<>:norm AND is_current""",
                pid=pid,
                ds=ds,
                key=key,
                norm=norm,
            )
        alias = (
            sql(
                conn,
                """SELECT id,parcel_id FROM core.parcel_identifier WHERE dataset_id=:ds AND
            identifier_type=:key AND normalized_value=:norm AND is_current""",
                ds=ds,
                key=key,
                norm=norm,
            )
            .mappings()
            .first()
        )
        if alias is not None and alias["parcel_id"] != pid:
            raise Reject("identifier collision", "conflicting")
        if alias:
            sql(
                conn,
                """UPDATE core.parcel_identifier SET last_seen=greatest(last_seen,:day),
                first_seen=least(first_seen,:day) WHERE id=:id""",
                day=day,
                id=alias["id"],
            )
        else:
            sql(
                conn,
                """INSERT INTO core.parcel_identifier(parcel_id,dataset_id,identifier_type,identifier_value,
                normalized_value,is_current,source_record_id,first_seen,last_seen)
                VALUES(:pid,:ds,:key,:raw,:norm,:current,:record,:day,:day)""",
                pid=pid,
                ds=ds,
                key=key,
                raw=raw,
                norm=norm,
                current=is_latest,
                record=record,
                day=day,
            )
    # Compare to the last observation as of this source date. A backfill must
    # neither replace today's geometry nor report a change against a future version.
    previous_same = sql(
        conn,
        """SELECT ST_Equals(geom,ST_GeomFromEWKB(:wkb)) AND
        address IS NOT DISTINCT FROM CAST(:address AS text) AND primary_pin=:pin AND
        r.dataset_id=:ds AS same FROM core.parcel_geometry_version g
        JOIN provenance.source_record s ON s.id=g.source_record_id
        JOIN provenance.ingestion_run r ON r.id=s.run_id
        WHERE g.parcel_id=:pid AND g.observed_at<=CAST(:day AS date)::timestamp AT TIME ZONE 'UTC'
        ORDER BY g.observed_at DESC,r.published_at DESC,g.id LIMIT 1""",
        wkb=wkb,
        address=f.get("address"),
        pin=f["pin"],
        pid=pid,
        ds=ds,
        day=day,
    ).scalar()
    if is_latest:
        sql(
            conn,
            "UPDATE core.parcel_geometry_version SET is_current=false WHERE parcel_id=:pid AND is_current",
            pid=pid,
        )
    # Even an unchanged shape needs its own dated citation for this distinct run.
    sql(
        conn,
        """INSERT INTO core.parcel_geometry_version(parcel_id,source_record_id,geom,observed_at,
        is_current,primary_pin,normalized_pin,address) VALUES(:pid,:record,ST_GeomFromEWKB(:wkb),
        CAST(:day AS date)::timestamp AT TIME ZONE 'UTC',:current,:pin,:norm,:address)""",
        pid=pid,
        record=record,
        wkb=wkb,
        day=day,
        current=is_latest,
        pin=f["pin"],
        norm=normalized,
        address=f.get("address"),
    )
    for key in ("deeded_acres", "gis_acres", "address"):
        if f.get(key) is not None:
            _claim(conn, pid, key, {"value": f[key]}, record, row, manifest, key, day)
    if f.get("address"):
        sql(
            conn,
            """INSERT INTO core.address(parcel_id,source_record_id,raw_address,normalized_address)
            VALUES(:pid,:rec,:raw,:norm)""",
            pid=pid,
            rec=record,
            raw=f["address"],
            norm=" ".join(f["address"].upper().split()),
        )
    return {
        "new_parcels": int(new),
        "changed": int(previous_same is False),
        "usable_addresses": int(bool(f.get("address"))),
    }


def _assessor(conn, ds, jurisdiction, manifest, record, row, day, attempt):
    f = row.fields
    if manifest.join_identifier == "pin":
        pid = _resolve(conn, ds, jurisdiction, f)
    else:
        # Alternate namespaces are explicitly configured after inspecting the workbook;
        # an assessor string must never match an unrelated dataset's alias by chance.
        pid = sql(
            conn,
            """SELECT p.id FROM core.parcel p JOIN core.parcel_identifier i ON i.parcel_id=p.id
            JOIN provenance.source_dataset d ON d.id=i.dataset_id WHERE p.jurisdiction_id=:j
            AND p.parcel_state='active' AND d.dataset_key=:source AND d.enabled AND i.is_current
            AND i.identifier_type=:kind AND i.normalized_value=:value""",
            j=jurisdiction,
            source=manifest.join_dataset,
            kind=manifest.join_identifier,
            value=f["pin"].strip().upper(),
        ).scalar_one_or_none()
    if pid is None:
        raise Reject("unmatched assessor parcel", "unmatched")
    if not f.get("owner") or not f["owner"].strip():
        raise Reject("missing assessor-listed owner")
    # Reuse this source's designation of this same parcel owner only. A matching
    # name, address or agent on another parcel does not establish entity identity.
    previous = (
        sql(
            conn,
            """SELECT o.party_id,p.canonical_name,o.observed_on,r.dataset_id,
        c.value->>'tax_year' AS tax_year FROM core.ownership_record o JOIN core.party p ON o.party_id=p.id
        JOIN evidence.claim c ON c.id=o.claim_id JOIN evidence.claim_support cs ON cs.claim_id=c.id
        JOIN provenance.source_record sr ON sr.id=cs.source_record_id JOIN provenance.ingestion_run r ON r.id=sr.run_id
        WHERE o.parcel_id=:pid AND o.observed_on<=:day ORDER BY
        o.observed_on DESC,r.published_at DESC,o.id""",
            pid=pid,
            ds=ds,
            day=day,
        )
        .mappings()
        .all()
    )
    owner = f["owner"]
    same = next(
        (p for p in previous if p["canonical_name"] == owner and p["dataset_id"] == ds),
        None,
    )
    party = (
        same["party_id"]
        if same
        else sql(
            conn,
            """INSERT INTO core.party(party_type,canonical_name)
        VALUES(:kind,:name) RETURNING id""",
            kind="organization"
            if re.search(r"\b(LLC|INC|CORP|LP|LTD)\.?$", owner, re.IGNORECASE)
            else "unknown",
            name=owner,
        ).scalar_one()
    )
    conflict = any(
        p["canonical_name"] != owner and p["observed_on"] == day for p in previous
    )
    if conflict:
        _review(
            conn,
            attempt,
            "competing assessor-listed owners on the same observation date",
            record,
            row.locator,
        )
    claim = _claim(
        conn,
        pid,
        "assessor_listed_owner",
        {"value": owner, "party_id": str(party), "tax_year": f.get("tax_year")},
        record,
        row,
        manifest,
        "owner",
        day,
        "verified",
    )
    sql(
        conn,
        """INSERT INTO core.ownership_record(parcel_id,party_id,ownership_kind,claim_id,observed_on)
        VALUES(:pid,:party,'assessor_listed_owner',:claim,:day)""",
        pid=pid,
        party=party,
        claim=claim,
        day=day,
    )
    for key in ("assessed_value", "tax_year", "mailing_address"):
        if f.get(key) is not None:
            value = {"value": f[key]}
            if key == "assessed_value":
                value.update(currency="USD", tax_year=f.get("tax_year"))
            _claim(conn, pid, key, value, record, row, manifest, key, day)
    return {
        "matched_owners": 1,
        "changed": int(bool(previous) and previous[0]["canonical_name"] != owner),
        "conflicting": int(conflict),
    }


def retry_attempt(attempt_id: str) -> dict:
    with engine().connect() as conn:
        previous = (
            sql(
                conn,
                """SELECT d.dataset_key,a.raw_object_key,a.artifact_sha256,a.observed_on,a.mode
            FROM provenance.ingestion_attempt a JOIN provenance.source_dataset d ON d.id=a.dataset_id
            WHERE a.id=:attempt""",
                attempt=attempt_id,
            )
            .mappings()
            .one_or_none()
        )
    if not previous or not previous["raw_object_key"]:
        raise ValueError(
            "attempt has no retained input; supply a permitted artifact to import"
        )
    if previous["dataset_key"] in PRIVATE_GWINNETT_DATASETS:
        from .gwinnett_bootstrap import import_private, private_objects, private_policy

        if previous["mode"] != "manual":
            raise PermissionError(
                "the private Gwinnett evaluation requires a manual attempt"
            )
        key = previous["raw_object_key"]
        if not re.fullmatch(r"[0-9a-f]{64}", key) or previous["artifact_sha256"] != key:
            raise ValueError("invalid retained private object reference")
        with private_import_diagnostics():
            with engine().begin() as conn:
                private_policy(conn, previous["dataset_key"])
            root = private_objects()
            path = root / key[:2] / key
            if path.resolve(strict=True) != path:
                raise PermissionError("unexpected link in the private object path")
            with path.open("rb") as stream:
                if file_digest(stream, "sha256").hexdigest() != key:
                    raise OSError(
                        "stored private artifact failed integrity verification"
                    )
            return import_private(
                previous["dataset_key"], path, previous["observed_on"]
            )
    result = import_snapshot(
        previous["dataset_key"],
        lambda: storage.get_bytes(previous["raw_object_key"]),
        previous["observed_on"],
        method=previous["mode"],
        reconcile=True,
    )
    if result["accepted"]:
        with engine().begin() as conn:
            sql(
                conn,
                """INSERT INTO staging.review_resolution(review_item_id,attempt_id,reason)
                SELECT id,:retry,'original observation date republished' FROM staging.review_item
                WHERE attempt_id=:original AND reason='retry retained snapshot at its original observation date'
                ON CONFLICT(review_item_id) DO NOTHING""",
                retry=result["attempt_id"],
                original=attempt_id,
            )
    return result


def _recover_unmatched(conn, manifest, ds, attempt, run, rows):
    pending = (
        sql(
            conn,
            """SELECT q.id,q.source_record_id,s.locator FROM staging.review_item q
        JOIN provenance.source_record s ON s.id=q.source_record_id
        WHERE s.run_id=:run AND q.reason='unmatched assessor parcel'
        AND NOT EXISTS (SELECT 1 FROM staging.review_resolution completed WHERE completed.review_item_id=q.id)
        ORDER BY q.created_at,q.id""",
            run=run["id"],
        )
        .mappings()
        .all()
    )
    jurisdiction = sql(
        conn,
        "SELECT id FROM core.jurisdiction WHERE county_fips=:fips",
        fips=manifest.county_fips,
    ).scalar_one()
    quality = dict(run["metrics"])
    by_locator = {json.dumps(row.locator, sort_keys=True): row for row in rows}
    recovered = 0
    for item in pending:
        row = by_locator[json.dumps(item["locator"], sort_keys=True)]
        try:
            with conn.begin_nested():
                deltas = _assessor(
                    conn,
                    ds,
                    jurisdiction,
                    manifest,
                    item["source_record_id"],
                    row,
                    run["observed_on"],
                    attempt,
                )
        except Reject:
            continue
        sql(
            conn,
            """INSERT INTO staging.review_resolution(review_item_id,attempt_id,reason)
            VALUES(:item,:attempt,'matched after parcel became available')""",
            item=item["id"],
            attempt=attempt,
        )
        for metric, count in deltas.items():
            quality[metric] += count
        recovered += 1
    quality["accepted"] += recovered
    quality["quarantined"] -= recovered
    quality["unmatched"] -= recovered
    if recovered:
        sql(
            conn,
            "UPDATE provenance.ingestion_run SET metrics=CAST(:metrics AS jsonb) WHERE id=:run",
            metrics=json.dumps(quality),
            run=run["id"],
        )
    return quality, recovered
