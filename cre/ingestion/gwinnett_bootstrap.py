"""First publication and exact replay of a manually acquired private county baseline."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import ijson
from psycopg.types.json import Jsonb

from cre.db import engine

from .contract import (
    Row,
    SnapshotError,
    _fields,
    _headers,
    _row_error,
    iter_assessor_rows,
)
from .service import _dataset, _finish, _review, sql

PRIVATE_DATABASE = "cre_gwinnett_internal"
PRIVATE_OBJECTS = Path(__file__).resolve().parents[2] / ".local/gwinnett-review/objects"
COLUMNS = {
    "gwinnett_parcels": """ordinal bigint, record_id uuid, ext_id text, digest text, loc jsonb,
        pin text, taxpin text, lrsn text, gid text, address text, deeded numeric, acres numeric,
        geometry_json text, srid integer, reason text""",
    "gwinnett_assessor": """ordinal bigint, record_id uuid, ext_id text, digest text, loc jsonb,
        pin text, lrsn text, owner text, details jsonb, reason text""",
}


def private_objects():
    directory = Path(os.getenv("CRE_STORAGE_DIR", PRIVATE_OBJECTS)).resolve()
    if (
        directory != PRIVATE_OBJECTS.resolve()
        or os.getenv("CRE_S3_BUCKET")
        or os.getenv("CRE_ENV") == "production"
    ):
        raise PermissionError("use the private local Gwinnett object directory")
    return directory


def private_policy(conn, key):
    if key not in COLUMNS or engine().url.host not in ("localhost", "127.0.0.1", "::1"):
        raise PermissionError(
            "Gwinnett internal imports require the private local database"
        )
    restricted = sql(
        conn,
        """SELECT current_database() = :db
        AND NOT has_database_privilege('cre_runtime', current_database(), 'CONNECT')
        AND NOT has_database_privilege('cre_worker', current_database(), 'CONNECT')
        AND NOT EXISTS (SELECT FROM pg_database d,
           LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
           WHERE d.datname=current_database() AND a.grantee=0 AND a.privilege_type='CONNECT')""",
        db=PRIVATE_DATABASE,
    ).scalar_one()
    if not restricted:
        raise PermissionError(
            "private database must deny PUBLIC, runtime and worker connections"
        )
    # Hold the source policies through retention, replay, or publication. An
    # assessor observation also relies on the private parcel namespace.
    required = {key, "gwinnett_parcels"}
    policies = sql(
        conn,
        """SELECT dataset_key, enabled AND NOT shared_display AND NOT export_allowed
        FROM provenance.source_dataset WHERE dataset_key IN (:key, 'gwinnett_parcels')
        ORDER BY dataset_key FOR SHARE""",
        key=key,
    )
    if {name for name, private in policies if private} != required:
        raise PermissionError("county sources must be enabled for private use only")
    ds, m = _dataset(conn, key, lock=True)
    m.authorize("manual")
    if (
        m.county_fips != "13135"
        or m.rights.methods != ["manual"]
        or m.rights.shared_display
        or m.rights.export_allowed
    ):
        raise PermissionError("expected a manually acquired, private Gwinnett source")
    return ds, m


def retain(path: Path):
    root = private_objects()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    digest = hashlib.sha256()
    with path.open("rb") as src, tempfile.NamedTemporaryFile(dir=root) as tmp:
        while chunk := src.read(4 * 1024**2):
            digest.update(chunk)
            tmp.write(chunk)
        tmp.flush()
        os.fsync(tmp.fileno())
        key = digest.hexdigest()
        if path.resolve().is_relative_to(root) and path.name != key:
            raise OSError("retained object does not match its content address")
        dest = root / key[:2] / key
        dest.parent.mkdir(mode=0o700, exist_ok=True)
        try:
            os.link(tmp.name, dest)
        except FileExistsError:
            with dest.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != key:
                    raise OSError("retained county artifact failed digest verification")
    return dest


def parcel_rows(manifest, path):
    with path.open("rb") as stream:
        if next(ijson.items(stream, "type"), None) != "FeatureCollection":
            raise SnapshotError("expected county FeatureCollection")
        stream.seek(0)
        name = next(ijson.items(stream, "crs.properties.name"), None)
        # The reviewed Hub export includes an explicit native projection.
        projection = {
            "EPSG:2240": 2240,
            "EPSG:4326": 4326,
            "urn:ogc:def:crs:EPSG::2240": 2240,
            "urn:ogc:def:crs:EPSG::4326": 4326,
        }
        if name not in projection:
            raise SnapshotError("missing or unreviewed county export projection")
        stream.seek(0)
        for index, feature in enumerate(
            ijson.items(stream, "features.item", use_float=True)
        ):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise SnapshotError(f"unexpected GeoJSON feature at ordinal {index}")
            props = feature.get("properties")
            if not isinstance(props, dict):
                raise SnapshotError(f"missing properties at feature {index}")
            _headers(props, manifest)
            fields = _fields(props, manifest)
            yield Row(
                fields,
                {"feature": index},
                str(fields.get("global_id") or fields.get("pin") or f"feature:{index}"),
                feature,
                feature.get("geometry"),
                projection[name],
                _row_error(fields),
            )


def copy_rows(conn, key, m, path):
    parcels = m.kind == "parcels"
    name = "incoming_parcel" if parcels else "incoming_assessor"
    conn.exec_driver_sql(f"CREATE TEMP TABLE {name} ({COLUMNS[key]}) ON COMMIT DROP")
    digests = []
    rows = parcel_rows(m, path) if parcels else iter_assessor_rows(m, path.read_bytes())
    with (
        conn.connection.driver_connection.cursor() as cur,
        cur.copy(f"COPY {name} FROM STDIN") as copy,
    ):
        for i, row in enumerate(rows):
            digest = row.digest()
            digests.append(digest)
            f = row.fields
            base = (i, uuid4(), row.external_id, digest, Jsonb(row.locator), f["pin"])
            if parcels:
                values = (
                    f.get("taxpin"),
                    f.get("lrsn"),
                    f.get("global_id"),
                    f.get("address"),
                    f.get("deeded_acres"),
                    f.get("gis_acres"),
                    json.dumps(row.geometry, separators=(",", ":"))
                    if row.geometry
                    else None,
                    row.srid,
                )
            else:
                details = {
                    k: v
                    for k, v in f.items()
                    if k not in ("pin", "source_lrsn", "owner") and v is not None
                }
                values = (f.get("source_lrsn"), f.get("owner"), Jsonb(details))
            copy.write_row((*base, *values, row.error))
            if (i + 1) % 100000 == 0:
                print(
                    f"{key}: staged {i + 1:,} source rows", file=sys.stderr, flush=True
                )
    if not digests:
        raise SnapshotError("empty county snapshot requires review")
    fp = hashlib.sha256("".join(sorted(digests)).encode()).hexdigest()
    return fp, len(digests)


def publish(conn, ds, m, attempt, artifact, observed):
    sql(conn, "SELECT pg_advisory_xact_lock(174274,13135)")
    existing = (
        sql(
            conn,
            """SELECT id, metrics FROM provenance.ingestion_run WHERE
        dataset_id=:ds AND raw_object_key=:obj AND observed_on=:day AND mapping_version=:version""",
            ds=ds,
            obj=artifact.name,
            day=observed,
            version=m.mapping_version,
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        quality = existing["metrics"]
        return (
            existing["id"],
            "replayed" if quality["accepted"] else "quarantined",
            quality,
        )
    if sql(
        conn,
        """SELECT EXISTS(SELECT FROM provenance.ingestion_run WHERE dataset_id=:ds
           AND (metrics->>'accepted')::bigint IS DISTINCT FROM 0)""",
        ds=ds,
    ).scalar_one():
        raise SnapshotError(
            "a different baseline already exists; review changes before updating it"
        )
    if (
        m.kind == "assessor"
        and not sql(
            conn,
            """SELECT EXISTS(SELECT FROM
        provenance.ingestion_run r JOIN provenance.source_dataset d ON r.dataset_id=d.id
        WHERE d.dataset_key='gwinnett_parcels' AND d.enabled AND (r.metrics->>'accepted')::bigint>0)""",
        ).scalar_one()
    ):
        raise SnapshotError(
            "publish the private parcel baseline before joining assessor records"
        )
    fp, count = copy_rows(conn, m.dataset_key, m, artifact)
    # A new container or JSON representation can contain exactly the same
    # held records. Preserve their original locators and this attempt's digest.
    held = (
        sql(
            conn,
            """SELECT id, metrics FROM provenance.ingestion_run WHERE dataset_id=:ds
        AND input_fingerprint=:fp AND mapping_version=:v AND observed_on=:day
        AND (metrics->>'accepted')::bigint=0""",
            ds=ds,
            fp=fp,
            v=m.mapping_version,
            day=observed,
        )
        .mappings()
        .one_or_none()
    )
    if held:
        return held["id"], "quarantined", held["metrics"]
    run = sql(
        conn,
        """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,
        mapping_version,manifest,observed_on,raw_object_key,artifact_sha256,metrics)
        VALUES (:ds,:fp,:v,CAST(:m AS jsonb),:day,:obj,:obj,'{}') RETURNING id""",
        ds=ds,
        fp=fp,
        v=m.mapping_version,
        m=m.model_dump_json(),
        day=observed,
        obj=artifact.name,
    ).scalar_one()
    jurisdiction = sql(
        conn,
        """INSERT INTO core.jurisdiction(county_fips,county_name,state_code)
        VALUES (:fips,:name,:state) ON CONFLICT(county_fips) DO UPDATE SET county_name=EXCLUDED.county_name
        RETURNING id""",
        fips=m.county_fips,
        name=m.county_name,
        state=m.state_code,
    ).scalar_one()
    conn.exec_driver_sql("""CREATE TEMP TABLE batch (run_id uuid,attempt_id uuid,dataset_id uuid,
        jurisdiction_id uuid,observed date,columns jsonb) ON COMMIT DROP""")
    sql(
        conn,
        "INSERT INTO batch VALUES (:run,:attempt,:ds,:j,:day,CAST(:cols AS jsonb))",
        run=run,
        attempt=attempt,
        ds=ds,
        j=jurisdiction,
        day=observed,
        cols=json.dumps(m.columns),
    )
    print(
        f"{m.dataset_key}: validating and publishing {count:,} staged rows",
        file=sys.stderr,
        flush=True,
    )
    statements = files("cre.ingestion").joinpath(f"bootstrap_{m.kind}.sql").read_text()
    with conn.connection.driver_connection.cursor() as cur:
        cur.execute(statements, prepare=False)
    quality = dict(sql(conn, "SELECT * FROM batch_counts").mappings().one())
    if (
        quality["read"] != count
        or quality["accepted"] + quality["quarantined"] != count
    ):
        raise ValueError("county publication counts do not reconcile")
    parcels = m.kind == "parcels"
    addresses = (
        sql(
            conn,
            """SELECT count(*) FROM core.address a JOIN provenance.source_record s
        ON s.id=a.source_record_id WHERE s.run_id=:run""",
            run=run,
        ).scalar_one()
        if parcels
        else 0
    )
    quality.update(
        changed=0,
        missing_from_snapshot=0,
        usable_addresses=addresses,
        matched_owners=0 if parcels else quality["accepted"],
        new_parcels=quality["accepted"] if parcels else 0,
    )
    sql(
        conn,
        "UPDATE provenance.ingestion_run SET metrics=CAST(:q AS jsonb) WHERE id=:id",
        q=json.dumps(quality),
        id=run,
    )
    return run, "published" if quality["accepted"] else "quarantined", quality


def import_private(key: str, path: Path, observed: date) -> dict:
    private_objects()
    with engine().begin() as conn:
        ds, m = private_policy(conn, key)
        attempt = sql(
            conn,
            """INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on)
            VALUES (:ds,'manual','acquiring',:day) RETURNING id""",
            ds=ds,
            day=observed,
        ).scalar_one()
    try:
        with engine().begin() as conn:
            _, current = private_policy(conn, key)
            if current != m:
                raise SnapshotError("county source policy changed")
            artifact = retain(path)
            sql(
                conn,
                """UPDATE provenance.ingestion_attempt SET raw_object_key=:obj,
                artifact_sha256=:obj,status='staging' WHERE id=:id""",
                obj=artifact.name,
                id=attempt,
            )
        with engine().begin() as conn:
            sql(conn, "SET LOCAL work_mem='64MB'")
            _, current = private_policy(conn, key)
            if current != m:
                raise SnapshotError("county source policy changed")
            run, status, quality = publish(conn, ds, m, attempt, artifact, observed)
            _finish(conn, attempt, status, run=run, quality=quality)
        return {
            "run_id": str(run),
            "attempt_id": str(attempt),
            "status": status,
            **quality,
        }
    except Exception as exc:
        status = "quarantined" if isinstance(exc, SnapshotError) else "failed"
        # A database error can contain a copy of the failing private data row.
        detail = (
            str(exc)[:500]
            if isinstance(exc, (SnapshotError, PermissionError))
            else type(exc).__name__
        )
        with engine().begin() as conn:
            _finish(conn, attempt, status, detail)
            if status == "quarantined":
                _review(conn, attempt, detail)
        raise
