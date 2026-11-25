"""Read the privately retained Site Address Point export for an operator lookup."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import ijson

from .contract import SnapshotError, normalize_pin
from .gwinnett_bootstrap import PRIVATE_OBJECTS
from .service import sql

DATASET = "gwinnett_address_points"
DIGEST = "aca97218b60b875732c9ea0f0754209a280bf01bc3cf33156b8362ad96280bf0"
CATALOG_DIGEST = "5270e881d21eb122b74310b8ec9e1f6b3562e2092ad025ffa7fa4fbc42286ef7"
ITEM = "37205351432348f887d1bef3eb80ddcd"
TERMS = f"https://gcgis-gwinnettcountyga.hub.arcgis.com/api/v3/datasets/{ITEM}_0"
ELIGIBLE = {"Primary", "Secondary", "Tertiary"}


def text_key(value):
    return " ".join((value or "").upper().replace(",", " ").split())


def address_keys(row):
    """Only remove address presentation or qualifiers absent from the input."""
    full = text_key(row["FULLADDR"])
    keys = {full: "full_address"} if full else {}
    street = text_key(f"{row['ADDRNUM'] or ''} {row['FULLNAME'] or ''}")
    if (
        not row["ADDRNUM"]
        or not row["FULLNAME"]
        or any(row.get(key) for key in ("PREADDRNUM", "ADDRNUMSUF", "ADDRRANGE"))
    ):
        return keys
    units = []
    for kind, number in (("UNITTYPE", "UNITID"), ("ALTUNITTYPE", "ALTUNITID")):
        typ, uid = text_key(row[kind]), text_key(row[number])
        if bool(typ) != bool(uid):
            return keys
        if uid:
            units.append((typ, uid))
    rendered = " ".join([street, *(f"{typ} {uid}" for typ, uid in units)])
    if not units or rendered != full:
        return keys
    # A unit supplied without a building is searched across every building at
    # the same street. Distinct supporting parcel IDs stay distinct.
    for typ, uid in units:
        keys.setdefault(f"{street} {typ} {uid}", "unit_id")
        keys.setdefault(f"{street} {uid}", "unit_id")
    if len(units) == 2:
        keys[f"{street} {units[0][1]} - {units[1][1]}"] = "unit_pair"
    return keys


def checked_file(path, digest):
    if path.resolve() != path or path.stat().st_mode & 0o077 or not path.is_file():
        raise PermissionError("Expected an owner-only retained address-point source")
    stream = path.open("rb")
    try:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise SnapshotError(f"Unreviewed Gwinnett address-point file: {path.name}")
        stream.seek(0)
        return stream
    except BaseException:
        stream.close()
        raise


def point_hits(addresses):
    directory = PRIVATE_OBJECTS.parent / "address-points"
    if any(
        p.is_symlink() or p.stat().st_mode & 0o077
        for p in (directory, directory.parent)
    ):
        raise PermissionError("Expected a private Gwinnett evaluation directory")
    with checked_file(directory / "catalog.json", CATALOG_DIGEST):
        pass
    queries = defaultdict(list)
    for idx, query in enumerate(addresses):
        queries[text_key(query)].append(idx)

    hits = []
    with checked_file(directory / "address-points.geojson", DIGEST) as stream:
        # The digest pins the reviewed FeatureCollection, EPSG:2240, all
        # 416,661 unique OBJECTIDs, property schema and point geometries.
        for feature in ijson.items(stream, "features.item", use_float=True):
            row = feature["properties"]
            if row["STATUS"] not in ELIGIBLE:
                continue
            for key, method in address_keys(row).items():
                if key in queries:
                    x, y = feature["geometry"]["coordinates"]
                    hits.append(
                        {
                            "indices": queries[key],
                            "method": method,
                            "oid": row["OBJECTID"],
                            "site": row["SITEADDID"],
                            "pin": normalize_pin(row["PIN"] or ""),
                            "status": row["STATUS"],
                            "x": x,
                            "y": y,
                        }
                    )
    return hits


COVERING = """
    WITH points AS (
      SELECT DISTINCT oid,x,y FROM jsonb_to_recordset(CAST(:hits AS jsonb))
      AS v(oid bigint,x double precision,y double precision)
    )
    SELECT v.oid,p.id AS parcel_id,g.normalized_pin,s.id AS source_record_id,s.locator
    FROM points v
    JOIN core.parcel_geometry_version g ON g.is_current AND
      ST_Covers(g.geom, ST_Transform(ST_SetSRID(ST_MakePoint(v.x,v.y),2240),4326))
    JOIN core.parcel p ON p.id=g.parcel_id AND p.parcel_state='active'
    JOIN core.jurisdiction j ON j.id=p.jurisdiction_id AND j.county_fips='13135'
    JOIN provenance.source_record s ON s.id=g.source_record_id AND s.run_id=:gis_run
    ORDER BY v.oid,g.normalized_pin
"""


def _verified_identity_point(parcel, pin, evidence):
    """Recognize the already verified child/common or held polygon relationship."""
    if (
        parcel["normalized_pin"] != pin
        or evidence.get("dataset") != DATASET
        or evidence.get("artifact_sha256") != DIGEST
        or evidence.get("locator", {}).get("object_id")
        not in parcel.get("verified_point_oids", ())
    ):
        return False
    covers = evidence["covering_pins"]
    if parcel["geometry_role"] == "shared_common_polygon":
        return covers == [parcel["geometry_pin"]]
    return (
        parcel["geometry_role"] == "direct_polygon"
        and parcel["geometry_pin"] == pin
        and not covers
    )


def combine(base, observations):
    parcels = {
        p["parcel_id"]: {**p, "address_sources": list(p["address_sources"])}
        for p in base
    }
    rejected = []
    for parcel, pin, evidence in observations:
        if parcel is None:
            reviewed = [
                p
                for p in parcels.values()
                if _verified_identity_point(p, pin, evidence)
            ]
            if len(reviewed) == 1:
                reviewed[0]["address_sources"].append(
                    {**evidence, "verified_geometry_role": reviewed[0]["geometry_role"]}
                )
            else:
                rejected.append({"point_pin": pin, **evidence})
            continue
        match = parcels.setdefault(
            parcel["parcel_id"], {**parcel, "address_sources": []}
        )
        match["address_sources"].append(evidence)
    matches = sorted(
        parcels.values(), key=lambda p: (p["normalized_pin"], p["parcel_id"])
    )
    if len(matches) == 1:
        supported_pin = matches[0]["normalized_pin"]
        for row in rejected:
            if row["point_pin"] != supported_pin or any(
                pin != supported_pin for pin in row.get("covering_pins", ())
            ):
                return [], rejected
    return matches, rejected


def augment(conn, addresses, matches, gis_run):
    hits = point_hits(addresses)
    covering = defaultdict(list)
    for row in sql(conn, COVERING, hits=json.dumps(hits), gis_run=gis_run).mappings():
        covering[row["oid"]].append(row)
    observations = [[] for _ in addresses]
    for hit in hits:
        rows = covering[hit["oid"]]
        evidence = {
            "dataset": DATASET,
            "artifact_sha256": DIGEST,
            "locator": {
                "layer": 0,
                "object_id": hit["oid"],
                "site_address_id": hit["site"],
                "field": "FULLADDR",
            },
            "method": hit["method"],
            "status": hit["status"],
        }
        if hit["method"] != "full_address":
            evidence["unit_fields"] = [
                "ADDRNUM",
                "FULLNAME",
                "UNITTYPE",
                "UNITID",
                "ALTUNITTYPE",
                "ALTUNITID",
            ]
        parcel = None
        if len(rows) == 1 and hit["pin"] == rows[0]["normalized_pin"]:
            row = rows[0]
            parcel = {
                "parcel_id": str(row["parcel_id"]),
                "normalized_pin": row["normalized_pin"],
                "pin_source": {
                    "dataset": "gwinnett_parcels",
                    "run_id": gis_run,
                    "source_record_id": str(row["source_record_id"]),
                    "locator": {**row["locator"], "field": "PIN"},
                },
                "address_sources": [],
            }
        else:
            evidence["covering_pins"] = [r["normalized_pin"] for r in rows]
        for idx in hit["indices"]:
            observations[idx].append((parcel, hit["pin"], evidence))
    results, rejected = [], []
    for base, observed in zip(matches, observations, strict=True):
        candidates, review = combine(base, observed)
        results.append(candidates)
        rejected.append(review)
    source = {
        "artifact_sha256": DIGEST,
        "observed_on": "2026-11-20",
        "county_item": ITEM,
        "layer": 0,
        "features": 416661,
        "terms": TERMS,
        "catalog_sha256": CATALOG_DIGEST,
        "lookup_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return source, results, rejected
