"""Authorized operator commands. Each import consumes a local, permitted artifact."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from cre.db import engine

from .contract import (
    PRIVATE_GWINNETT_DATASETS,
    Manifest,
    inspect_workbook,
    normalize_pin,
)
from .demo import seed
from .service import (
    import_snapshot,
    private_import_diagnostics,
    register,
    retry_attempt,
    sql,
)


def benchmark(path: Path):
    """Independent address/point queries, each with a human-labeled expected PIN."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        labels = list(csv.DictReader(stream))
    if not labels:
        raise ValueError("benchmark CSV is empty")
    seen = set()
    failures = []
    with engine().connect() as conn:
        for n, row in enumerate(labels, 2):
            key = (row["county_fips"], normalize_pin(row["expected_pin"]))
            if key in seen or not key[1]:
                raise ValueError(f"duplicate or missing labeled parcel on CSV line {n}")
            seen.add(key)
            if row.get("longitude") and row.get("latitude"):
                matches = (
                    sql(
                        conn,
                        """SELECT normalized_pin FROM core.visible_parcel WHERE county_fips=:fips
                    AND ST_Covers(geom,ST_SetSRID(ST_MakePoint(:x,:y),4326))""",
                        fips=key[0],
                        x=float(row["longitude"]),
                        y=float(row["latitude"]),
                    )
                    .scalars()
                    .all()
                )
            elif row.get("address"):
                matches = (
                    sql(
                        conn,
                        """SELECT normalized_pin FROM core.visible_parcel WHERE county_fips=:fips
                    AND lower(trim(address))=lower(trim(:address))""",
                        fips=key[0],
                        address=row["address"],
                    )
                    .scalars()
                    .all()
                )
            else:
                raise ValueError(f"address or coordinates required on CSV line {n}")
            if matches != [key[1]]:
                failures.append({"line": n, "expected": key[1], "matched": matches})
    accuracy = (len(labels) - len(failures)) / len(labels)
    return {
        "count": len(labels),
        "accuracy": accuracy,
        "failures": failures,
        "passed": len(labels) >= 100 and accuracy >= 0.98,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    registration = commands.add_parser(
        "register", help="register or update an operator-reviewed source contract"
    )
    registration.add_argument("path", type=Path)
    registration.add_argument(
        "--if-missing",
        action="store_true",
        help="preserve any existing operator decision",
    )
    commands.add_parser(
        "retry",
        help="retry retained source input and resolve newly matchable assessor rows",
    ).add_argument("attempt_id")
    imp = commands.add_parser(
        "import", help="publish an authorized manual source snapshot"
    )
    imp.add_argument("dataset")
    imp.add_argument("path", type=Path)
    imp.add_argument("--as-of", type=date.fromisoformat, required=True)
    commands.add_parser(
        "inspect-workbook", help="inspect sheet and column names on a permitted input"
    ).add_argument("path", type=Path)
    demo = commands.add_parser(
        "demo", help="import fictional Gwinnett-area samples in a separate jurisdiction"
    )
    demo.add_argument("--count", type=int, default=3)
    commands.add_parser(
        "health", help="latest 100 audited ingestion attempts and quality reports"
    )
    commands.add_parser("review", help="latest 100 source exceptions and locators")
    commands.add_parser(
        "benchmark",
        help="verify externally labeled CSV against production parcel lookup",
    ).add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "register":
        result = {
            "dataset_id": register(
                Manifest.model_validate_json(args.path.read_bytes()),
                only_if_missing=args.if_missing,
            )
        }
    elif args.command == "import":
        if args.dataset in PRIVATE_GWINNETT_DATASETS:
            from .gwinnett_bootstrap import import_private

            with private_import_diagnostics():
                result = import_private(args.dataset, args.path, args.as_of)
        else:
            result = import_snapshot(args.dataset, args.path.read_bytes, args.as_of)
    elif args.command == "retry":
        result = retry_attempt(args.attempt_id)
    elif args.command == "inspect-workbook":
        result = inspect_workbook(args.path.read_bytes())
    elif args.command == "demo":
        if not 1 <= args.count <= 1000:
            parser.error("--count must be 1..1000")
        result = seed(args.count)
    elif args.command == "benchmark":
        result = benchmark(args.path)
    else:
        query = """SELECT a.id,d.dataset_key,a.status,a.observed_on,a.started_at,a.completed_at,a.run_id,
            a.detail,a.quality FROM provenance.ingestion_attempt a JOIN provenance.source_dataset d ON d.id=a.dataset_id
            ORDER BY a.started_at DESC LIMIT 100"""
        if args.command == "review":
            query = """SELECT q.id,q.attempt_id,d.dataset_key,q.created_at,q.reason,q.locator,q.source_record_id
                FROM staging.review_item q JOIN provenance.ingestion_attempt a ON a.id=q.attempt_id
                JOIN provenance.source_dataset d ON d.id=a.dataset_id
                WHERE NOT EXISTS (SELECT 1 FROM staging.review_resolution resolved WHERE resolved.review_item_id=q.id)
                ORDER BY q.created_at DESC LIMIT 100"""
        with engine().connect() as conn:
            result = [dict(row) for row in sql(conn, query).mappings()]
    print(json.dumps(result, indent=2, default=str))
    if args.command in {"import", "retry"} and result["status"] == "quarantined":
        return 2
    return 1 if args.command == "benchmark" and not result["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
