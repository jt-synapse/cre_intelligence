"""Resolve private county condo identities against separately cited common-area geometry."""

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

import ijson

from . import gwinnett_address_points as ap
from .contract import SnapshotError, normalize_pin
from .gwinnett_bootstrap import PRIVATE_OBJECTS
from .gwinnett_companions import ARCHIVE_SHA, OWNER, SHEET
from .service import sql

DATASET = "gwinnett_condo_parcel_id"
RECEIPT_SHA = "acdd8595c973dbbd352068aa6c342994ec87f4f93b6f6680f457910a03e1bc23"


def street(value):
    return (value or "").strip().upper()


def read_table():
    directory = PRIVATE_OBJECTS.parent / "condo-source"
    if any(
        p.is_symlink() or p.stat().st_mode & 0o077
        for p in (directory, directory.parent)
    ):
        raise PermissionError("Expected the private county condo evaluation directory")
    with ap.checked_file(directory / "receipt.json", RECEIPT_SHA) as f:
        receipt = json.load(f)
    with ap.checked_file(directory / "browser-data.json", receipt["terms_sha256"]):
        pass
    rows = []
    for page in receipt["pages"]:
        with ap.checked_file(directory / page["file"], page["sha256"]) as f:
            rows.extend(feature["attributes"] for feature in json.load(f)["features"])
    if len(rows) != receipt["rows"]:
        raise SnapshotError("Incomplete countywide condo identity table")
    source = {
        "origin": receipt["url"],
        "table": receipt["table"],
        "rows": receipt["rows"],
        "observed_on": receipt["retrieved_utc"][:10],
        "receipt_sha256": RECEIPT_SHA,
        "terms": receipt["terms_url"],
        "terms_sha256": receipt["terms_sha256"],
        "coverage": "Full county condo table",
        "lookup_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return rows, source


def point_records(children):
    directory = PRIVATE_OBJECTS.parent / "address-points"
    found = defaultdict(list)
    with ap.checked_file(directory / "catalog.json", ap.CATALOG_DIGEST):
        pass
    with ap.checked_file(directory / "address-points.geojson", ap.DIGEST) as stream:
        for feature in ijson.items(stream, "features.item", use_float=True):
            row = feature["properties"]
            pin = normalize_pin(row["PIN"] or "")
            if pin in children and row["STATUS"] in ap.ELIGIBLE:
                x, y = feature["geometry"]["coordinates"]
                found[pin].append(
                    {
                        "oid": row["OBJECTID"],
                        "site": row["SITEADDID"],
                        "common": normalize_pin(row["COMMONPIN"] or ""),
                        "status": row["STATUS"],
                        "kind": row["POINTTYPE"],
                        "x": x,
                        "y": y,
                    }
                )
    return found


def raw_geometry_context(children, points, digest):
    """Find every direct child shape and all original shapes that could cover a point."""
    direct = set()
    possible = []
    xy = sorted((p["x"], p["y"], p["oid"]) for group in points.values() for p in group)
    xs = [x for x, _, _ in xy]
    with ap.checked_file(PRIVATE_OBJECTS / digest[:2] / digest, digest) as stream:
        for feature in ijson.items(stream, "features.item", use_float=True):
            pin = normalize_pin(feature["properties"]["PIN"] or "")
            if pin in children:
                direct.add(pin)
            shape = feature.get("geometry")
            if not xy or not shape:
                continue
            polygons = (
                shape["coordinates"]
                if shape["type"] == "MultiPolygon"
                else [shape["coordinates"]]
            )
            rings = [polygon[0] for polygon in polygons if polygon and polygon[0]]
            if not rings:
                continue
            lo = min(x for ring in rings for x, y in ring)
            hi = max(x for ring in rings for x, y in ring)
            start, end = bisect_left(xs, lo), bisect_right(xs, hi)
            if start == end:
                continue
            bottom = min(y for ring in rings for x, y in ring)
            top = max(y for ring in rings for x, y in ring)
            if any(bottom <= y <= top for _, y, _ in xy[start:end]):
                possible.append({"pin": pin, "shape": shape})
    return direct, possible


COVERING = """
    WITH pt AS MATERIALIZED (
      SELECT oid,common, ST_SetSRID(ST_MakePoint(x,y),2240) AS geom
      FROM jsonb_to_recordset(CAST(:points AS jsonb))
      AS v(oid bigint,common text,x double precision,y double precision)
    ), shape AS MATERIALIZED (
      SELECT pin, ST_SetSRID(ST_GeomFromGeoJSON(shape),2240) AS geom
      FROM jsonb_to_recordset(CAST(:shapes AS jsonb)) AS v(pin text,shape jsonb)
    ), native AS (
      SELECT pt.oid,count(*)=1 AND bool_and(shape.pin=pt.common AND
          CASE WHEN ST_IsValid(shape.geom) THEN ST_Contains(shape.geom,pt.geom) ELSE false END) AS sole_parent
      FROM pt JOIN shape ON shape.geom && pt.geom AND
        CASE WHEN ST_IsValid(shape.geom) THEN ST_Covers(shape.geom,pt.geom) ELSE true END
      GROUP BY pt.oid
    )
    SELECT pt.oid,g.parcel_id,g.normalized_pin,s.id AS source_record_id,s.locator,
      native.sole_parent AND ST_Contains(g.geom,ST_Transform(pt.geom,4326)) AS interior
    FROM pt JOIN native ON native.oid=pt.oid
    JOIN core.parcel_geometry_version g ON g.is_current AND ST_Covers(g.geom,ST_Transform(pt.geom,4326))
    JOIN core.parcel p ON p.id=g.parcel_id AND p.parcel_state='active'
    JOIN core.jurisdiction j ON j.id=p.jurisdiction_id AND j.county_fips='13135'
    JOIN provenance.source_record s ON s.id=g.source_record_id AND s.run_id=:run
"""


def table_citation(row, field):
    return {
        "dataset": DATASET,
        "receipt_sha256": RECEIPT_SHA,
        "locator": {
            "layer": 10,
            "object_id": row["OBJECTID"],
            **({"field": field} if isinstance(field, str) else {"fields": field}),
        },
    }


def resolve_units(rows, addresses, *, assessor, points, covering, raw_direct, sources):
    from .gwinnett_situs import OWNER_SHA

    queries = defaultdict(list)
    for i, address in enumerate(addresses):
        queries[street(address)].append(i)
    counts = [
        Counter(normalize_pin(r["PIN"] or "") for r in rows),
        Counter(r["RPIN"] for r in rows),
        Counter(r["LRSN"] for r in rows),
    ]
    matches, reviews = [[] for _ in addresses], [[] for _ in addresses]
    for row in rows:
        indices = queries.get(street(row["LOCADDR"]))
        if not indices:
            continue
        child = normalize_pin(row["PIN"] or "")
        common = normalize_pin(row["COMMON_PIN"] or "")
        tax, lrs = row["RPIN"], row["LRSN"]
        roll = assessor.get(tax)
        records = points.get(child, [])
        primary = [
            p for p in records if p["status"] == "Primary" and p["kind"] == "Condo"
        ]
        reason = None
        if not child or not common or child == common or not tax or lrs is None:
            reason = "missing_or_conflicting_condo_keys"
        elif any(c[k] != 1 for c, k in zip(counts, (child, tax, lrs), strict=True)):
            reason = "duplicate_condo_key"
        elif (
            not roll
            or roll[1] != tax
            or str(roll[2]) != str(lrs)
            or street(roll[3]) != street(row["LOCADDR"])
        ):
            reason = "condo_tax_roll_disagreement"
        elif child in raw_direct:
            reason = "direct_child_feature_requires_review"
        elif not primary or any(p["common"] != common for p in records):
            reason = "missing_or_conflicting_common_point_key"
        else:
            parents = []
            for p in records:
                covers = covering.get(p["oid"], [])
                if (
                    len(covers) != 1
                    or not covers[0]["interior"]
                    or covers[0]["normalized_pin"] != common
                ):
                    reason = "common_polygon_containment_disagreement"
                    break
                parents.append(covers[0])
            if not reason and len({p["parcel_id"] for p in parents}) != 1:
                reason = "multiple_common_geometries"
        if reason:
            entry = {"point_pin": child, "reason": reason, **table_citation(row, "PIN")}
            for i in indices:
                reviews[i].append(entry)
            continue

        parent = parents[0]
        geometry = {
            "dataset": "gwinnett_parcels",
            "run_id": sources["gwinnett_parcels"]["run_id"],
            "source_record_id": str(parent["source_record_id"]),
            "locator": {**parent["locator"], "field": "geometry"},
        }
        point_citations = [
            {
                "dataset": ap.DATASET,
                "artifact_sha256": ap.DIGEST,
                "locator": {
                    "layer": 0,
                    "object_id": p["oid"],
                    "site_address_id": p["site"],
                    "fields": ["PIN", "COMMONPIN", "POINTTYPE", "STATUS", "geometry"],
                },
            }
            for p in records
        ]
        roll_source = {
            "dataset": "gwinnett_assessor",
            "run_id": sources["gwinnett_assessor"]["run_id"],
            "artifact_sha256": ARCHIVE_SHA,
            "workbook_sha256": OWNER_SHA,
        }
        row_locator = {"workbook": OWNER, "sheet": SHEET, "row": roll[0]}
        candidate = {
            "parcel_id": f"gwinnett:condo:{child}",
            "normalized_pin": child,
            "identity_method": "county_condo_crosswalk",
            "identity_scope": "private_evaluation",
            "pin_source": table_citation(row, "PIN"),
            "tax_key_sources": [
                table_citation(row, ["RPIN", "LRSN"]),
                {
                    **roll_source,
                    "locator": {**row_locator, "fields": ["PIN", "LRSNum"]},
                },
            ],
            "address_sources": [
                table_citation(row, "LOCADDR"),
                {**roll_source, "locator": {**row_locator, "field": "PROPERTYSTREET"}},
            ],
            "common_pin_source": table_citation(row, "COMMON_PIN"),
            "geometry_role": "shared_common_polygon",
            "geometry_pin": common,
            "geometry_parcel_id": str(parent["parcel_id"]),
            "geometry_source": geometry,
            "point_sources": point_citations,
            "verified_point_oids": sorted(p["oid"] for p in records),
        }
        for i in indices:
            matches[i].append(candidate)
    return matches, reviews


def candidates(conn, addresses, sources, *, assessor):
    rows, metadata = read_table()
    queries = {street(a) for a in addresses}
    children = {
        normalize_pin(row["PIN"] or "")
        for row in rows
        if street(row["LOCADDR"]) in queries
    }
    gis = sources["gwinnett_parcels"]
    metadata["source_sha256"] = {
        "gwinnett_parcels": gis["artifact_sha256"],
        "gwinnett_assessor": sources["gwinnett_assessor"]["artifact_sha256"],
        ap.DATASET: ap.DIGEST,
    }
    if not children:
        return metadata, [[] for _ in addresses], [[] for _ in addresses]
    points = point_records(children)
    direct, shapes = raw_geometry_context(children, points, gis["artifact_sha256"])
    found = defaultdict(list)
    records = [pt for group in points.values() for pt in group]
    if records:
        for row in sql(
            conn,
            COVERING,
            points=json.dumps(records),
            shapes=json.dumps(shapes),
            run=gis["run_id"],
        ).mappings():
            found[row["oid"]].append(row)
    hits, unresolved = resolve_units(
        rows,
        addresses,
        assessor=assessor,
        points=points,
        covering=found,
        raw_direct=direct,
        sources=sources,
    )
    return metadata, hits, unresolved
