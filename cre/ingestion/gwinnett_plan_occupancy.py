"""Exact address evidence from the privately retained October 2026 county reports."""

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import ijson

from . import gwinnett_address_points as points
from .contract import normalize_pin
from .gwinnett_bootstrap import PRIVATE_OBJECTS
from .service import sql

DATASET = "gwinnett_plan_occupancy"
ROOT = PRIVATE_OBJECTS.parent / "plan-occupancy-collection"
# The manifest pins the selection, indexes, county reports and retained portal evidence.
MANIFEST_SHA256 = "3a9ae23a0727f6819a7fcde7c53c317357e9fb1f0870f7bc014372ac84ad6bed"
COMPLETE_MANIFEST_SHA256 = "398542e52518440b44fdd0a774611ba684ac19f1a29707be8e4a2350a61656d6"
CUTOFF = date(2026, 11, 8)
UNIT = r"([A-Z0-9]+(?:[-.][A-Z0-9]+)*)"
SUITE_PREFIX = r"(?:(?:STE|SUITE) |# ?)"
PAIR = re.compile(rf"(.+) (?:BLDG|BUILDING) {UNIT} {SUITE_PREFIX}{UNIT}")
SUITE = re.compile(rf"(.+) {SUITE_PREFIX}{UNIT}")
SITE_QUALIFIERS = re.compile(
    rf"(?:(?:BLDG|BUILDING) {UNIT}(?: (?:{SUITE_PREFIX}|(?:APT|UNIT) ){UNIT})?"
    rf"|(?:{SUITE_PREFIX}|(?:APT|UNIT) ){UNIT}|\d[A-Z0-9.-]*(?: - {UNIT})?)"
)


def address_forms(address):
    """Render only explicit unit fields, preserving every part of the location."""
    full = points.text_key(address)
    pair = PAIR.fullmatch(full)
    if pair:
        street, building, suite = pair.groups()
        return {full, f"{street} {building} - {suite}"}
    single = SUITE.fullmatch(full)
    if single:
        street, suite = single.groups()
        return {full, f"{street} {suite}"}
    return {full} if full else set()


def address_hits(addresses, records):
    index = defaultdict(set)
    for i, row in enumerate(records):
        for key in address_forms(row["address"]):
            index[key].add(i)
    hits = []
    for address in addresses:
        indices = set()
        for key in address_forms(address):
            indices.update(index.get(key, ()))
        hits.append([records[i] for i in sorted(indices)])
    return hits


def load_collection():
    root = ROOT
    manifest_path = root / "manifest.json"
    digest = MANIFEST_SHA256
    completed = root.parent / "october-completion" / "manifest.json"
    if completed.exists():
        root = root.parent
        manifest_path = completed
        digest = COMPLETE_MANIFEST_SHA256
    with points.checked_file(manifest_path, digest) as stream:
        manifest = json.load(stream)
    records = []
    for source in manifest["indexes"]:
        with points.checked_file(root / source["path"], source["sha256"]) as stream:
            rows = json.load(stream)
        if len(rows) != source["records"]:
            raise ValueError("Plan and occupancy index count differs from the release")
        records.extend(rows)
    return {
        "manifest_sha256": digest,
        "selection_sha256": manifest["selection_sha256"],
        "indexes": manifest["indexes"],
        "lookup_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }, records


def qualified(row):
    return (
        row["eligible"] is True
        and bool(row["parcel_id"] and row.get("status_date"))
        and date.fromisoformat(row["status_date"]) <= CUTOFF
    )


def primary_sites(addresses, features):
    """Use county street fields to find a single parcel shared by all its site points."""
    prefixes = []
    for address in addresses:
        words = points.text_key(address).split()
        keys = []
        for n in range(len(words), 1, -1):
            tail = " ".join(words[n:])
            # A partially matched street name is never a unit qualifier.
            if not tail or SITE_QUALIFIERS.fullmatch(tail):
                keys.append(" ".join(words[:n]))
        prefixes.append(keys)
    sites = {
        key: {"street": key, "pins": set(), "primary": []}
        for keys in prefixes
        for key in keys
    }
    for feature in features:
        row = feature["properties"]
        if (
            row["STATUS"] not in points.ELIGIBLE
            or not row["ADDRNUM"]
            or not row["FULLNAME"]
        ):
            continue
        if any(row.get(k) for k in ("PREADDRNUM", "ADDRNUMSUF", "ADDRRANGE")):
            continue
        street = points.text_key(f"{row['ADDRNUM']} {row['FULLNAME']}")
        if street in sites:
            site = sites[street]
            pin = normalize_pin(row["PIN"] or "")
            site["pins"].add(pin)
            if row["STATUS"] == "Primary":
                x, y = feature["geometry"]["coordinates"]
                site["primary"].append({"oid": row["OBJECTID"], "x": x, "y": y})
    witnesses = []
    for keys in prefixes:
        site = next((sites[k] for k in keys if sites[k]["pins"]), None)
        if (
            site
            and site["primary"]
            and len(site["pins"]) == 1
            and "" not in site["pins"]
        ):
            witnesses.append(
                {
                    "street": site["street"],
                    "pin": next(iter(site["pins"])),
                    "primary": site["primary"],
                }
            )
        else:
            witnesses.append(None)
    return witnesses


def covered_site(site, coverage, gis_run):
    if not site:
        return None
    # A second primary on a different parcel leaves the site's identity unresolved.
    covered_parcels = {
        (row["normalized_pin"], row["parcel_id"])
        for point in site["primary"]
        for row in coverage.get(point["oid"], ())
    }
    if len(covered_parcels) != 1:
        return None
    for point in sorted(site["primary"], key=lambda p: p["oid"]):
        rows = coverage.get(point["oid"], ())
        if len(rows) == 1 and rows[0]["normalized_pin"] == site["pin"]:
            row = rows[0]
            return {
                "normalized_pin": row["normalized_pin"],
                "parcel_id": str(row["parcel_id"]),
                "pin_source": {
                    "dataset": "gwinnett_parcels",
                    "run_id": gis_run,
                    "source_record_id": str(row["source_record_id"]),
                    "locator": {**row["locator"], "field": "PIN"},
                },
                "address_sources": [
                    {
                        "dataset": points.DATASET,
                        "artifact_sha256": points.DIGEST,
                        "site_street": site["street"],
                        "method": "site_parcel_corroboration",
                        "locator": {"layer": 0, "object_id": point["oid"]},
                    }
                ],
            }
    return None


def site_witnesses(conn, addresses, gis_run):
    path = PRIVATE_OBJECTS.parent / "address-points/address-points.geojson"
    with points.checked_file(path, points.DIGEST) as stream:
        sites = primary_sites(
            addresses, ijson.items(stream, "features.item", use_float=True)
        )
    primary = [point for site in sites if site for point in site["primary"]]
    coverage = defaultdict(list)
    for row in sql(
        conn, points.COVERING, hits=json.dumps(primary), gis_run=gis_run
    ).mappings():
        coverage[row["oid"]].append(row)
    return [covered_site(site, coverage, gis_run) for site in sites]


def resolve(previous, documents, witness, *, held):
    if not documents or len(previous) > 1:
        return previous
    pins = {normalize_pin(row["parcel_id"]) for row in documents if row["parcel_id"]}
    if previous:
        pins.add(previous[0]["normalized_pin"])
    if len(pins) != 1:
        return []
    eligible = [row for row in documents if qualified(row)]
    if not eligible:
        return previous
    candidate = previous[0] if previous else witness
    if (
        not candidate
        or (not previous and held)
        or candidate["normalized_pin"] not in pins
    ):
        return previous
    evidence = [{**row, "dataset": DATASET} for row in eligible]
    return [
        {**candidate, "address_sources": [*candidate["address_sources"], *evidence]}
    ]


def augment(conn, addresses, matches, gis_run, rejected_points, rejected_identities):
    metadata, records = load_collection()
    hits = address_hits(addresses, records)
    needs_witness = [
        i
        for i, rows in enumerate(hits)
        if not matches[i]
        and not rejected_points[i]
        and not rejected_identities[i]
        and any(qualified(row) for row in rows)
    ]
    witnesses = {}
    if needs_witness:
        witnesses = dict(
            zip(
                needs_witness,
                site_witnesses(conn, [addresses[i] for i in needs_witness], gis_run),
                strict=True,
            )
        )
    results = [
        resolve(
            base,
            rows,
            witnesses.get(i),
            held=bool(rejected_points[i] or rejected_identities[i]),
        )
        for i, (base, rows) in enumerate(zip(matches, hits, strict=True))
    ]
    return metadata, results, hits
