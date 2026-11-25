"""Private operator lookup and frozen permit benchmark for the November Gwinnett snapshots."""

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from cre.db import engine
from cre.ingestion import gwinnett_address_points
from cre.ingestion.contract import Manifest, normalize_pin
from cre.ingestion.gwinnett_bootstrap import PRIVATE_DATABASE, PRIVATE_OBJECTS
from cre.ingestion.gwinnett_companions import ARCHIVE_SHA, OWNER, SHEET
from cre.ingestion.service import sql

FIPS = "13135"
RELEASES = {
    "gwinnett_parcels": {
        "observed_on": "2026-11-20",
        "mapping_version": "2",
        "artifact_sha256": "7bc547068cfaea1d884f9819bc304dabb79872f9d5c254185753561d5b4222e0",
    },
    "gwinnett_assessor": {
        "observed_on": "2026-11-22",
        "mapping_version": "2",
        "artifact_sha256": ARCHIVE_SHA,
    },
}


def check_sources(rows):
    if sorted(row["dataset_key"] for row in rows) != sorted(RELEASES):
        raise ValueError("Expected one reviewed publication for each county dataset")
    sources = {}
    for row in rows:
        key = row["dataset_key"]
        source = RELEASES[key]
        if (
            str(row["observed_on"]) != source["observed_on"]
            or row["mapping_version"] != source["mapping_version"]
            or row["artifact_sha256"] != source["artifact_sha256"]
            or row["raw_object_key"] != source["artifact_sha256"]
        ):
            raise ValueError("County publication differs from the reviewed snapshot")
        if not row["enabled"] or row["shared_display"] or row["export_allowed"]:
            raise PermissionError(
                "Both county sources must be enabled for private use only"
            )
        for policy in (row["manifest"], row["published_manifest"]):
            manifest = Manifest.model_validate(policy)
            manifest.authorize("manual")
            rights = manifest.rights
            if (
                manifest.county_fips != FIPS
                or manifest.dataset_key != key
                or rights.methods != ["manual"]
                or rights.shared_display
                or rights.export_allowed
            ):
                raise PermissionError(
                    "Expected manual, private Gwinnett source policies"
                )
        sources[key] = {**source, "run_id": str(row["run_id"])}
    return sources


def reviewed_publications(conn):
    rows = (
        sql(
            conn,
            """
        SELECT d.dataset_key,d.manifest,d.enabled,d.shared_display,d.export_allowed,
               r.id AS run_id,r.observed_on,r.mapping_version,r.artifact_sha256,r.raw_object_key,r.manifest AS published_manifest
        FROM provenance.source_dataset d JOIN provenance.ingestion_run r ON r.dataset_id=d.id
        WHERE d.dataset_key IN ('gwinnett_parcels','gwinnett_assessor') AND (r.metrics->>'accepted')::bigint>0
    """,
        )
        .mappings()
        .all()
    )
    return check_sources(rows)


def preflight(conn):
    isolated = sql(
        conn,
        """
        SELECT current_database() = :database AND current_setting('transaction_read_only')='on'
          AND NOT has_database_privilege('cre_runtime',current_database(),'CONNECT')
          AND NOT has_database_privilege('cre_worker',current_database(),'CONNECT')
          AND NOT EXISTS (
            SELECT FROM pg_database d, LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
            WHERE d.datname=current_database() AND a.grantee=0 AND a.privilege_type='CONNECT')
        """,
        database=PRIVATE_DATABASE,
    ).scalar_one()
    if not isolated:
        raise PermissionError("Private read-only database access check failed")
    sources = reviewed_publications(conn)
    if not sql(
        conn, "SELECT to_regclass('staging.gwinnett_situs_address') IS NOT NULL"
    ).scalar_one():
        raise ValueError("Build the private situs index before looking up addresses")
    ready = sql(
        conn,
        """
        SELECT EXISTS(SELECT FROM staging.gwinnett_situs_address a
            JOIN provenance.source_record s ON s.id=a.source_record_id
            WHERE s.run_id=:run AND a.source_field='PROPERTYSTREET'
              AND s.locator->>'workbook'=:owner AND s.locator->>'sheet'=:sheet)
        """,
        run=sources["gwinnett_assessor"]["run_id"],
        owner=OWNER,
        sheet=SHEET,
    ).scalar_one()
    if not ready:
        raise ValueError("Situs index is missing the reviewed assessor publication")
    return sources


# Retrieve from the two street-address fields before looking at any benchmark label.
# The same parcel can have an exact match from each source, each with its own citation.
LOOKUP = """
    WITH queries(idx,address) AS (VALUES {query_values}), hits AS MATERIALIZED (
        SELECT q.idx,g.parcel_id,g.source_record_id,'ADDRESS' AS field
        FROM queries q JOIN core.parcel_geometry_version g ON lower(trim(g.address))=lower(trim(q.address))
        WHERE g.is_current
        UNION ALL
        SELECT q.idx,a.parcel_id,a.source_record_id,a.source_field
        FROM queries q JOIN staging.gwinnett_situs_address a ON lower(trim(a.raw_address))=lower(trim(q.address))
        WHERE a.source_field='PROPERTYSTREET'
    )
    SELECT h.idx,h.parcel_id,g.normalized_pin,gs.id AS gis_record,CAST(gs.locator AS text) AS gis_locator,
           h.field,s.id AS address_record,CAST(s.locator AS text) AS address_locator
    FROM hits h JOIN core.parcel p ON p.id=h.parcel_id AND p.parcel_state='active'
    JOIN core.jurisdiction j ON j.id=p.jurisdiction_id AND j.county_fips=:fips
    JOIN core.parcel_geometry_version g ON g.parcel_id=h.parcel_id AND g.is_current
    JOIN provenance.source_record gs ON gs.id=g.source_record_id AND gs.run_id=:gis_run
    JOIN provenance.source_record s ON s.id=h.source_record_id
    WHERE (h.field='ADDRESS' AND s.id=gs.id) OR (h.field='PROPERTYSTREET' AND s.run_id=:assessor_run)
    ORDER BY h.idx,g.normalized_pin,h.parcel_id,h.field,s.id
"""


def citation(dataset, run_id, record, locator, field):
    return {
        "dataset": dataset,
        "run_id": run_id,
        "source_record_id": str(record),
        "locator": {**json.loads(locator), "field": field},
    }


def candidates(conn, addresses, sources):
    if not addresses or any(not address.strip() for address in addresses):
        raise ValueError(
            "Provide a nonblank street address, including the unit when present"
        )
    # Only generated integer indices appear in SQL. Every address is bound as a value.
    values = ", ".join(f"({i}, :address_{i})" for i in range(len(addresses)))
    params = {f"address_{i}": address for i, address in enumerate(addresses)}
    gis_run = sources["gwinnett_parcels"]["run_id"]
    assessor_run = sources["gwinnett_assessor"]["run_id"]
    rows = sql(
        conn,
        LOOKUP.format(query_values=values),
        **params,
        fips=FIPS,
        gis_run=gis_run,
        assessor_run=assessor_run,
    ).mappings()
    cases = [{} for _ in addresses]
    for row in rows:
        parcels = cases[row["idx"]]
        parcel_id = str(row["parcel_id"])
        if parcel_id not in parcels:
            parcels[parcel_id] = {
                "parcel_id": parcel_id,
                "normalized_pin": row["normalized_pin"],
                "pin_source": citation(
                    "gwinnett_parcels",
                    gis_run,
                    row["gis_record"],
                    row["gis_locator"],
                    "PIN",
                ),
                "address_sources": [],
            }
        dataset = (
            "gwinnett_parcels" if row["field"] == "ADDRESS" else "gwinnett_assessor"
        )
        parcels[parcel_id]["address_sources"].append(
            citation(
                dataset,
                sources[dataset]["run_id"],
                row["address_record"],
                row["address_locator"],
                row["field"],
            )
        )
    return [list(parcels.values()) for parcels in cases]


def _add_reviewed_identities(conn, addresses, sources, matches):
    from cre.ingestion import gwinnett_condos, gwinnett_held_identity
    from cre.ingestion.gwinnett_bootstrap import private_objects
    from cre.ingestion.gwinnett_situs import identity_roll, retained_owner_book

    # Both identity checks use the same verified countywide ownership roll.
    assessor = identity_roll(retained_owner_book(private_objects()))
    reviews = [[] for _ in addresses]
    for model in (gwinnett_condos, gwinnett_held_identity):
        metadata, candidates, rejected = model.candidates(
            conn, addresses, sources, assessor=assessor
        )
        sources[model.DATASET] = metadata
        for old, new, unresolved, issues in zip(
            matches, candidates, reviews, rejected, strict=True
        ):
            old.extend(new)
            unresolved.extend(issues)
    return reviews


def fetch_candidates(
    addresses, *, point_audit=None, identity_audit=None, document_audit=None
):
    db = engine()
    if db.url.database != PRIVATE_DATABASE or db.url.host not in (
        "127.0.0.1",
        "::1",
        "localhost",
    ):
        raise PermissionError(
            "Use scripts/gwinnett-internal with the private local database"
        )
    with db.begin() as conn:
        sql(conn, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        sql(conn, "SET LOCAL enable_parallel_hash=off")
        sources = preflight(conn)
        matches = candidates(conn, addresses, sources)
        with_identities = identity_audit is not None or document_audit is not None
        if with_identities:
            identity_reviews = _add_reviewed_identities(
                conn, addresses, sources, matches
            )
            if identity_audit is not None:
                identity_audit.extend(identity_reviews)
        if point_audit is not None or with_identities:
            source, matches, rejected = gwinnett_address_points.augment(
                conn, addresses, matches, sources["gwinnett_parcels"]["run_id"]
            )
            sources[gwinnett_address_points.DATASET] = source
            if point_audit is not None:
                point_audit.extend(rejected)
        if with_identities:
            # An unresolved identity at the exact submitted address can compete
            # with a single positive result from any of the other sources.
            for index, (found, unresolved) in enumerate(
                zip(matches, identity_reviews, strict=True)
            ):
                if len(found) == 1 and unresolved:
                    matches[index] = []
        if document_audit is not None:
            from cre.ingestion import gwinnett_plan_occupancy

            source, matches, documents = gwinnett_plan_occupancy.augment(
                conn,
                addresses,
                matches,
                sources["gwinnett_parcels"]["run_id"],
                rejected,
                identity_reviews,
            )
            sources[gwinnett_plan_occupancy.DATASET] = source
            document_audit.extend(documents)
        return sources, matches


def load_labels(path, digest):
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("Label digest differs from the recorded freeze")
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    if not {"address", "expected_pin", "county_fips", "source_case"} <= set(
        reader.fieldnames or []
    ):
        raise ValueError("Missing frozen benchmark fields")
    labels = list(reader)
    if len(labels) != 100:
        raise ValueError("Expected exactly 100 frozen address labels")
    seen = set()
    for row in labels:
        pin = normalize_pin(row["expected_pin"] or "")
        if (
            row["county_fips"] != FIPS
            or not (row["address"] or "").strip()
            or row.get("latitude")
            or row.get("longitude")
            or not pin
            or pin in seen
        ):
            raise ValueError(
                "Expected distinct labeled Gwinnett parcels and address-only queries"
            )
        seen.add(pin)
    return labels


def evaluate(labels, candidate_lists):
    outcomes = Counter()
    cases = []
    for line, (label, matches) in enumerate(
        zip(labels, candidate_lists, strict=True), 2
    ):
        pins = [parcel["normalized_pin"] for parcel in matches]
        expected = normalize_pin(label["expected_pin"])
        if not pins:
            outcome = "no_match"
        elif len(pins) > 1:
            outcome = "ambiguous"
        elif pins[0] == expected:
            outcome = "correct"
        else:
            outcome = "wrong_unique_pin"
        outcomes[outcome] += 1
        cases.append(
            {
                "csv_record": line,
                "case_id": label["source_case"],
                "outcome": outcome,
                "candidate_count": len(pins),
                "expected_among_candidates": expected in pins,
                "candidates": matches,
            }
        )
    count = len(labels)
    correct = outcomes["correct"]
    return {
        "count": count,
        "correct": correct,
        "accuracy": correct / count,
        "passed": count == 100 and correct >= 98,
        "outcomes": {
            k: outcomes[k]
            for k in ("correct", "no_match", "ambiguous", "wrong_unique_pin")
        },
    }, cases


def write_report(path, report, *, root=PRIVATE_OBJECTS.parent):
    directory = path.parent.resolve()
    if (
        root.is_symlink()
        or not directory.is_relative_to(root.resolve())
        or root.stat().st_mode & 0o077
    ):
        raise PermissionError(
            "Save benchmark evidence under the operator-only Gwinnett review directory"
        )
    # Link a complete, owner-only file into place. An existing report, source, or
    # symlink at the destination causes an atomic failure, including concurrent runs.
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8") as tmp:
        json.dump(report, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        os.link(tmp.name, directory / path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    lookup = commands.add_parser("lookup-address")
    lookup.add_argument("address")
    scorer = commands.add_parser("benchmark-addresses")
    for subcommand in (lookup, scorer):
        subcommand.add_argument(
            "--plan-occupancy",
            action="store_true",
            help="Include the private October plan and occupancy collection and parcel identity checks",
        )
        subcommand.add_argument(
            "--parcel-identities",
            action="store_true",
            help="Include address points and verified condo or held polygon identities in private lookup",
        )
        subcommand.add_argument(
            "--address-points",
            action="store_true",
            help="Include the pinned, locally retained county Site Address Point export",
        )
    scorer.add_argument("labels", type=Path)
    scorer.add_argument(
        "--sha256", required=True, help="SHA-256 recorded when this sample was frozen"
    )
    scorer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    reviews, identity_reviews, documents = [], [], []
    with_identities = args.parcel_identities or args.plan_occupancy
    with_points = args.address_points or with_identities
    options = {"point_audit": reviews} if with_points else {}
    if with_identities:
        options["identity_audit"] = identity_reviews
    if args.plan_occupancy:
        options["document_audit"] = documents
    if args.command == "lookup-address":
        sources, (matches,) = fetch_candidates([args.address], **options)
        status = (
            "no_match"
            if not matches
            else "unique"
            if len(matches) == 1
            else "ambiguous"
        )
        print(
            json.dumps(
                {
                    "sources": sources,
                    "status": status,
                    "candidate_count": len(matches),
                    "candidates": matches,
                    **(
                        {"unresolved_address_points": reviews[0]} if with_points else {}
                    ),
                    **(
                        {"unresolved_parcel_identities": identity_reviews[0]}
                        if with_identities
                        else {}
                    ),
                    **(
                        {"plan_occupancy_records": documents[0]}
                        if args.plan_occupancy
                        else {}
                    ),
                },
                indent=2,
            )
        )
        return 0
    labels = load_labels(args.labels, args.sha256)
    sources, matches = fetch_candidates([row["address"] for row in labels], **options)
    summary, cases = evaluate(labels, matches)
    if with_points:
        for case, unresolved in zip(cases, reviews, strict=True):
            case["unresolved_address_points"] = unresolved
    if with_identities:
        for case, unresolved in zip(cases, identity_reviews, strict=True):
            case["unresolved_parcel_identities"] = unresolved
    if args.plan_occupancy:
        for case, rows in zip(cases, documents, strict=True):
            case["plan_occupancy_records"] = rows
    write_report(
        args.output,
        {
            "scored_at_utc": datetime.now(UTC).isoformat(),
            "labels_sha256": args.sha256,
            "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "sources": sources,
            "county_fips": FIPS,
            "summary": summary,
            "cases": cases,
        },
    )
    print(json.dumps(summary))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SQLAlchemyError as exc:
        print(f"Private database check failed ({type(exc).__name__})", file=sys.stderr)
        sys.exit(2)
    except (OSError, KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
