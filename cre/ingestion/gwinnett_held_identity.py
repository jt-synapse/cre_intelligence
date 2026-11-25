"""Identify privately held GIS polygons whose only ambiguous alias is the LRSN."""

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

import ijson

from . import gwinnett_address_points as points
from .contract import SnapshotError, normalize_pin
from .gwinnett_bootstrap import PRIVATE_OBJECTS
from .gwinnett_companions import OWNER, SHEET
from .service import sql

DATASET = "gwinnett_held_identity"
HOLD_REASON = "colliding source identifiers"


def address_points(features, queries):
    """Retrieve exact primary building points and test competing building assignments."""
    primary, competing = defaultdict(list), defaultdict(set)
    for feature in features:
        p = feature["properties"]
        if p["STATUS"] not in points.ELIGIBLE:
            continue
        full = points.text_key(p["FULLADDR"])
        base = points.text_key(f"{p['ADDRNUM'] or ''} {p['FULLNAME'] or ''}")
        if base not in queries and full not in queries:
            continue
        pin = normalize_pin(p["PIN"] or "")
        for key in (full, base):
            if key in queries:
                competing[key].add(pin)
        if (
            full in queries
            and p["STATUS"] == "Primary"
            and p["POINTTYPE"] == "Building"
            and pin
        ):
            x, y = feature["geometry"]["coordinates"]
            primary[full].append(
                {
                    "oid": p["OBJECTID"],
                    "site": p["SITEADDID"],
                    "x": x,
                    "y": y,
                    "pin": pin,
                    "number": points.text_key(p["ADDRNUM"]),
                }
            )
    return primary, competing


def parcel_evidence(features, locations, holds):
    """Count source aliases and shortlist every original polygon envelope for each point."""
    by_x = sorted(locations, key=lambda p: p["x"])
    xs = [p["x"] for p in by_x]
    target_pins = {p["pin"] for p in locations}
    raw = []
    counts = [Counter() for _ in range(4)]
    envelopes = []
    for feature_number, feature in enumerate(features):
        props = feature["properties"]
        keys = (
            normalize_pin(props["PIN"] or ""),
            (props["TAXPIN"] or "").strip().upper(),
            (props["GlobalID"] or "").strip().upper(),
            str(props["LRSN"] or "").strip(),
        )
        for count, key in zip(counts, keys):
            count[key] += 1
        hold = holds.get(feature_number)
        if (
            keys[0] in target_pins
            and hold
            and hold["external_record_id"] == props["GlobalID"]
            and all(
                value is None or (math.isfinite(value) and value >= 0)
                for value in (
                    props.get("DEEDEDACREAGE"),
                    props.get("CALCULATEDACREAGE"),
                )
            )
        ):
            raw.append((keys, feature_number, props, hold))
        geom = feature["geometry"]
        try:
            if geom["type"] not in {"Polygon", "MultiPolygon"}:
                raise ValueError
            polygons = (
                geom["coordinates"]
                if geom["type"] == "MultiPolygon"
                else [geom["coordinates"]]
            )
            rings = [ring for poly in polygons for ring in poly]
            xx, yy = zip(*(xy for ring in rings for xy in ring), strict=True)
            if not all(map(math.isfinite, xx)) or not all(map(math.isfinite, yy)):
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise SnapshotError("Cannot establish a source polygon envelope") from exc
        # A malformed ring can still compete within its envelope. A null shape
        # blocks a positive interior claim there without passing it to GEOS.
        if not all(poly for poly in polygons) or any(
            len(ring) < 4 or ring[0] != ring[-1] for ring in rings
        ):
            geom = None
        left, right = bisect_left(xs, min(xx)), bisect_right(xs, max(xx))
        if left < right:
            south, north = min(yy), max(yy)
            for pt in by_x[left:right]:
                if south <= pt["y"] <= north:
                    envelopes.append(
                        {
                            "oid": pt["oid"],
                            "x": pt["x"],
                            "y": pt["y"],
                            "feature": feature_number,
                            "geom": geom,
                        }
                    )
    eligible = {}
    for keys, feature_number, props, hold in raw:
        if (
            all(keys)
            and all(counts[i][keys[i]] == 1 for i in range(3))
            and counts[3][keys[3]] > 1
        ):
            eligible[keys[0]] = {
                "feature": feature_number,
                "properties": props,
                "hold": hold,
                "lrsn_features": counts[3][keys[3]],
            }
    return eligible, envelopes


def unique_interiors(conn, envelopes):
    """Ambiguous covers, invalid neighboring shapes and boundary-only hits fail closed."""
    rows = sql(
        conn,
        """
        WITH shapes AS MATERIALIZED (
            SELECT oid, feature, ST_SetSRID(ST_GeomFromGeoJSON(geom),2240) AS g,
                ST_SetSRID(ST_MakePoint(x,y),2240) AS pt
            FROM jsonb_to_recordset(CAST(:payload AS jsonb))
                AS v(oid bigint, feature int, x float8, y float8, geom jsonb)
        ), checked AS (
            SELECT *, ST_IsValid(g,0) AND NOT ST_IsEmpty(g) AND ST_NDims(g)=2
                AND ST_IsValid(ST_Transform(g,4326),0) AS valid
            FROM shapes
        )
        SELECT oid, min(feature) FROM checked
        WHERE CASE WHEN valid THEN ST_Covers(g,pt) ELSE true END
        GROUP BY oid HAVING count(*)=1 AND bool_and(CASE WHEN valid THEN ST_Contains(g,pt) ELSE false END)
        """,
        payload=json.dumps(envelopes),
    )
    return dict(rows.all())


def source_holds(conn, source, reason):
    rows = sql(
        conn,
        """
        SELECT s.id AS source_record_id,s.external_record_id,s.locator,q.id AS review_id
        FROM staging.review_item q JOIN provenance.source_record s ON s.id=q.source_record_id
        WHERE s.run_id=:run AND q.reason=:reason AND q.locator=s.locator
          AND NOT EXISTS(SELECT FROM staging.review_resolution r WHERE r.review_item_id=q.id)
        """,
        run=source["run_id"],
        reason=reason,
    ).mappings()
    return rows


def citation(source, dataset, row, field):
    return {
        "dataset": dataset,
        "run_id": source["run_id"],
        "artifact_sha256": source["artifact_sha256"],
        "source_record_id": str(row["source_record_id"]),
        "locator": {**row["locator"], "field": field},
    }


def review_candidate(
    key, named, competing, parcel, interiors, source_row, tax, gis, roll
):
    """Return one corroborated primary identity, or its conflicting point evidence."""
    if tax is None or source_row is None:
        return None, None
    props, held = parcel["properties"], parcel["hold"]
    row_num, tax_key, assessor_lrsn, street = source_row
    if (
        tax_key != props["TAXPIN"]
        or points.text_key(street) != key
        or tax["locator"] != {"row": row_num, "sheet": SHEET, "workbook": OWNER}
    ):
        return None, None

    pin = normalize_pin(props["PIN"])
    evidence = [
        {
            "dataset": points.DATASET,
            "artifact_sha256": points.DIGEST,
            "locator": {
                "field": "FULLADDR",
                "layer": 0,
                "site_address_id": hit["site"],
                "object_id": hit["oid"],
            },
            "point_pin": pin,
            "status": "Primary",
            "point_type": "Building",
        }
        for hit in named
    ]
    if competing != {pin} or any(
        interiors.get(hit["oid"]) != parcel["feature"]
        or not hit["number"]
        or hit["number"] != points.text_key(props["ADDRESS"])
        for hit in named
    ):
        return None, {
            "point_pin": pin,
            "reason": "conflicting address, number or polygon coverage",
            "point_sources": evidence,
        }
    return {
        "parcel_id": f"gwinnett:held-gis:{props['GlobalID'].lower()}",
        "normalized_pin": pin,
        "geometry_pin": pin,
        "geometry_role": "direct_polygon",
        "identity_scope": "private_evaluation",
        "identity_method": "secondary_key_hold_with_corroborated_primary_identity",
        "pin_source": citation(gis, "gwinnett_parcels", held, "PIN"),
        "geometry_source": citation(gis, "gwinnett_parcels", held, "geometry"),
        "address_sources": [
            citation(roll, "gwinnett_assessor", tax, "PROPERTYSTREET"),
            *evidence,
        ],
        "verified_point_oids": sorted(hit["oid"] for hit in named),
        "taxpin_sources": [
            citation(gis, "gwinnett_parcels", held, "TAXPIN"),
            citation(roll, "gwinnett_assessor", tax, "PIN"),
        ],
        "secondary_identifier_review": {
            "review_id": str(held["review_id"]),
            "reason": HOLD_REASON,
            "gis_lrsn": props["LRSN"],
            "gis_features_sharing_lrsn": parcel["lrsn_features"],
            "assessor_lrsn": assessor_lrsn,
            "assessor_review_id": str(tax["review_id"]),
            "gis_source": citation(gis, "gwinnett_parcels", held, "LRSN"),
            "assessor_source": citation(roll, "gwinnett_assessor", tax, "LRSNum"),
        },
    }, None


def candidates(conn, addresses, sources, *, assessor):
    gis = sources["gwinnett_parcels"]
    roll = sources["gwinnett_assessor"]
    metadata = {
        "lookup_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "gis_sha256": gis["artifact_sha256"],
        "assessor_sha256": roll["artifact_sha256"],
        "points_sha256": points.DIGEST,
        "points_catalog_sha256": points.CATALOG_DIGEST,
        "scope": "private_reviewed_identity",
    }
    root = PRIVATE_OBJECTS.parent
    keys = [points.text_key(a) for a in addresses]
    with points.checked_file(
        root / "address-points" / "catalog.json", points.CATALOG_DIGEST
    ):
        pass
    with points.checked_file(
        root / "address-points" / "address-points.geojson", points.DIGEST
    ) as stream:
        primary, competing = address_points(
            ijson.items(stream, "features.item", use_float=True), set(keys)
        )
    # Published parcel identities already have their own lookup and GIS citation.
    pins = sorted({p["pin"] for hits in primary.values() for p in hits})
    active = set(
        sql(
            conn,
            """
        SELECT p.normalized_pin FROM core.parcel p JOIN core.jurisdiction j ON j.id=p.jurisdiction_id
        WHERE p.parcel_state='active' AND j.county_fips='13135' AND p.normalized_pin=ANY(:pins)
        """,
            pins=pins,
        ).scalars()
    )
    pending = [p for hits in primary.values() for p in hits if p["pin"] not in active]
    found, rejected = defaultdict(list), defaultdict(list)
    if pending:
        holds = {
            r["locator"]["feature"]: r for r in source_holds(conn, gis, HOLD_REASON)
        }
        with points.checked_file(
            root / "land-parcels.geojson", gis["artifact_sha256"]
        ) as stream:
            parcels, envelopes = parcel_evidence(
                ijson.items(stream, "features.item", use_float=True), pending, holds
            )
        interiors = unique_interiors(conn, envelopes)
        taxes = {
            r["external_record_id"]: r
            for r in source_holds(conn, roll, "unmatched assessor TAXPIN")
        }
        for key, hits in primary.items():
            for pin in sorted({hit["pin"] for hit in hits} & parcels.keys()):
                parcel = parcels[pin]
                taxpin = parcel["properties"]["TAXPIN"]
                named = [hit for hit in hits if hit["pin"] == pin]
                result, issue = review_candidate(
                    key,
                    named,
                    competing[key],
                    parcel,
                    interiors,
                    assessor.get(taxpin),
                    taxes.get(taxpin),
                    gis,
                    roll,
                )
                if result:
                    found[key].append(result)
                if issue:
                    rejected[key].append(issue)
    return metadata, [found[k] for k in keys], [rejected[k] for k in keys]
