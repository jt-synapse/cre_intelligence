"""Index literal property streets from the retained, privately published county roll."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from io import BytesIO
from zipfile import ZipFile

from openpyxl.reader.strings import read_string_table

from cre.db import engine
from cre.ingestion.contract import SnapshotError
from cre.ingestion.gwinnett_bootstrap import private_objects, private_policy
from cre.ingestion.gwinnett_companions import ARCHIVE_SHA, OWNER, SHEET, _literal, _rows
from cre.ingestion.gwinnett_lookup import reviewed_publications
from cre.ingestion.service import sql

OWNER_SHA = "feb978febd1fcd55a6edd1b3476d2e161d384a98886a02e81a91694ec2c52cfa"
OWNER_ROWS = 315343
FIELD = "PROPERTYSTREET"


def _street_rows(payload, *, land_record=False):
    """Read literal source cells and preserve the physical Excel row."""
    with ZipFile(BytesIO(payload)) as book:
        with book.open("xl/sharedStrings.xml") as stream:
            strings = read_string_table(stream)
        with book.open("xl/worksheets/sheet1.xml") as stream:
            rows = _rows(stream)
            number, headers = next(rows, (None, ()))
            names = {_literal(c, strings): c.attrib["r"][:-1] for c in headers}
            if (
                number != 1
                or len(names) != len(headers)
                or not {"PIN", FIELD} <= names.keys()
                or (land_record and "LRSNum" not in names)
            ):
                raise SnapshotError("missing or ambiguous ownership worksheet header")
            for expected, (number, row) in enumerate(rows, 2):
                if number != expected:
                    raise SnapshotError("incomplete ownership worksheet")
                pin = address = lrsn = None
                lrsn_ref = names["LRSNum"] + str(number) if land_record else None
                pin_ref, street_ref = (
                    names["PIN"] + str(number),
                    names[FIELD] + str(number),
                )
                for cell in row:
                    ref = cell.get("r")
                    if ref == pin_ref:
                        pin = _literal(cell, strings)
                    elif ref == street_ref:
                        address = _literal(cell, strings)
                    elif land_record and ref == lrsn_ref:
                        lrsn = _literal(cell, strings)
                    if (
                        address is not None
                        and pin is not None
                        and (not land_record or lrsn is not None)
                    ):
                        break
                if not pin:
                    raise SnapshotError("ownership worksheet is missing a source PIN")
                yield (
                    number,
                    pin,
                    lrsn,
                    address if address and address.strip() else None,
                )


def situs_rows(payload):
    for number, pin, _, address in _street_rows(payload):
        yield number, pin, address


def identity_roll(payload, *, expected_rows=OWNER_ROWS):
    by_taxpin = {}
    land_records = set()
    for number, pin, lrsn, street in _street_rows(payload, land_record=True):
        if pin in by_taxpin or not lrsn or not lrsn.isdecimal() or lrsn in land_records:
            raise SnapshotError(
                "missing or ambiguous identity keys in the assessor roll"
            )
        land_records.add(lrsn)
        by_taxpin[pin] = (number, pin, lrsn, street or "")
    if len(by_taxpin) != expected_rows:
        raise SnapshotError(
            "assessor identity roll row count differs from the reviewed release"
        )
    return by_taxpin


def _index_rows(conn, run, gis_run, rows, metrics):
    sql(
        conn,
        """CREATE TEMP TABLE situs_input(
        excel_row integer PRIMARY KEY, pin text NOT NULL UNIQUE, raw_address text) ON COMMIT DROP""",
    )
    with (
        conn.connection.driver_connection.cursor() as cur,
        cur.copy("COPY pg_temp.situs_input FROM STDIN") as out,
    ):
        for row in rows:
            out.write_row(row)
    sql(conn, "ANALYZE pg_temp.situs_input")
    counts = sql(
        conn,
        """SELECT
        (SELECT count(*) FROM pg_temp.situs_input),
        (SELECT count(*) FROM provenance.source_record WHERE run_id=:run)""",
        run=run,
    ).one()
    if counts != (metrics["read"], metrics["read"]):
        raise SnapshotError("ownership worksheet and snapshot row counts differ")

    # The source PIN and exact row locator are correlated. PostgreSQL estimates
    # their joint selectivity as nearly zero. Materialize their actual match set
    # before joining to claims or reviews, and avoid repeated full-table scans.
    sql(conn, "SET LOCAL enable_nestloop=off")
    sql(
        conn,
        """CREATE TEMP TABLE situs_source ON COMMIT DROP AS
        SELECT s.id AS source_record_id, i.excel_row, i.raw_address, s.locator
        FROM pg_temp.situs_input i JOIN provenance.source_record s ON s.run_id=:run
            AND s.external_record_id=i.pin
            AND s.locator=jsonb_build_object('workbook',CAST(:book AS text),'sheet',CAST(:sheet AS text),'row',i.excel_row)""",
        run=run,
        book=OWNER,
        sheet=SHEET,
    )
    sql(conn, "CREATE UNIQUE INDEX ON pg_temp.situs_source(source_record_id)")
    sql(conn, "ANALYZE pg_temp.situs_source")
    sql(
        conn,
        """CREATE TEMP TABLE situs_owner ON COMMIT DROP AS
        SELECT o.parcel_id, s.source_record_id FROM core.ownership_record o
        JOIN evidence.claim c ON c.id=o.claim_id AND c.subject_id=o.parcel_id
            AND c.subject_type='parcel' AND c.predicate='assessor_listed_owner'
            AND c.verification_state='verified' AND c.extraction_method='direct_mapping'
        JOIN evidence.claim_support cs ON cs.claim_id=c.id
        JOIN pg_temp.situs_source s ON s.source_record_id=cs.source_record_id
            AND cs.locator=s.locator || '{"field":"OWNERNAME1"}'::jsonb
        JOIN core.parcel p ON p.id=o.parcel_id
        JOIN core.jurisdiction j ON j.id=p.jurisdiction_id AND j.county_fips='13135'
        JOIN core.parcel_geometry_version g ON g.parcel_id=p.id AND g.is_current
        JOIN provenance.source_record gs ON gs.id=g.source_record_id AND gs.run_id=:gis_run
        WHERE o.ownership_kind=c.predicate""",
        gis_run=gis_run,
    )
    sql(conn, "CREATE UNIQUE INDEX ON pg_temp.situs_owner(source_record_id)")
    sql(conn, "ANALYZE pg_temp.situs_owner")
    sql(
        conn,
        """CREATE TEMP TABLE situs_link ON COMMIT DROP AS
        SELECT s.source_record_id, s.excel_row, s.raw_address, o.parcel_id, q.id AS hold_id
        FROM pg_temp.situs_source s
        LEFT JOIN pg_temp.situs_owner o ON o.source_record_id=s.source_record_id
        LEFT JOIN staging.review_item q ON q.source_record_id=s.source_record_id""",
    )
    sql(conn, "CREATE UNIQUE INDEX ON pg_temp.situs_link(excel_row)")
    sql(conn, "ANALYZE pg_temp.situs_link")
    total, accepted, held, invalid, addresses = sql(
        conn,
        """SELECT count(*), count(parcel_id),
        count(hold_id), count(*) FILTER (WHERE (hold_id IS NULL) = (parcel_id IS NULL)),
        count(*) FILTER (WHERE parcel_id IS NOT NULL AND raw_address IS NOT NULL)
        FROM pg_temp.situs_link""",
    ).one()
    if (
        total != metrics["read"]
        or accepted != metrics["accepted"]
        or held != metrics["quarantined"]
        or invalid
    ):
        raise SnapshotError(
            "ownership publication or held rows do not match the original worksheet"
        )

    exists = sql(
        conn, "SELECT to_regclass('staging.gwinnett_situs_address') IS NOT NULL"
    ).scalar_one()
    if not exists:
        sql(
            conn,
            """CREATE TABLE staging.gwinnett_situs_address (
            source_record_id uuid PRIMARY KEY REFERENCES provenance.source_record(id),
            parcel_id uuid NOT NULL REFERENCES core.parcel(id),
            raw_address text NOT NULL CHECK (btrim(raw_address) <> ''),
            source_field text NOT NULL DEFAULT 'PROPERTYSTREET' CHECK (source_field='PROPERTYSTREET'))""",
        )
        sql(
            conn,
            """INSERT INTO staging.gwinnett_situs_address(source_record_id, parcel_id, raw_address)
            SELECT source_record_id, parcel_id, raw_address FROM pg_temp.situs_link
            WHERE parcel_id IS NOT NULL AND raw_address IS NOT NULL""",
        )
    else:
        sql(
            conn,
            "LOCK TABLE staging.gwinnett_situs_address IN SHARE ROW EXCLUSIVE MODE",
        )
    sql(
        conn,
        """CREATE INDEX IF NOT EXISTS gwinnett_situs_address_lookup
        ON staging.gwinnett_situs_address(lower(btrim(raw_address)))""",
    )
    mismatch = sql(
        conn,
        """SELECT EXISTS (
        SELECT FROM staging.gwinnett_situs_address a FULL JOIN (
            SELECT * FROM pg_temp.situs_link WHERE parcel_id IS NOT NULL AND raw_address IS NOT NULL
        ) x ON x.source_record_id=a.source_record_id
        WHERE a.parcel_id IS DISTINCT FROM x.parcel_id OR a.raw_address IS DISTINCT FROM x.raw_address
           OR a.source_field IS DISTINCT FROM 'PROPERTYSTREET')""",
    ).scalar_one()
    if mismatch:
        raise SnapshotError("situs index differs from the verified ownership worksheet")
    if not exists:
        sql(conn, "ANALYZE staging.gwinnett_situs_address")
    sql(
        conn,
        "DROP TABLE pg_temp.situs_input, pg_temp.situs_source, pg_temp.situs_owner, pg_temp.situs_link",
    )
    return {
        "status": "replayed" if exists else "indexed",
        "source_rows": total,
        "accepted_rows": accepted,
        "indexed_addresses": addresses,
        "accepted_without_address": accepted - addresses,
    }


def retained_owner_book(root):
    path = root / ARCHIVE_SHA[:2] / ARCHIVE_SHA
    if path.resolve() != path or not path.is_file():
        raise SnapshotError("expected the retained private county archive")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA:
            raise SnapshotError(
                "retained archive digest differs from the reviewed release"
            )
        stream.seek(0)
        with ZipFile(stream) as archive:
            payload = archive.read(OWNER)
    if hashlib.sha256(payload).hexdigest() != OWNER_SHA:
        raise SnapshotError(
            "ownership workbook digest differs from the reviewed release"
        )
    return payload


def index_situs():
    root = private_objects()
    with engine().begin() as conn:
        _, manifest = private_policy(conn, "gwinnett_assessor")
        private_policy(conn, "gwinnett_parcels")
        sql(conn, "SELECT pg_advisory_xact_lock(174274,13135)")
        sql(conn, "SET LOCAL work_mem='64MB'")
        sql(conn, "SET LOCAL enable_parallel_hash=off")
        sources = reviewed_publications(conn)
        run = sources["gwinnett_assessor"]["run_id"]
        gis_run = sources["gwinnett_parcels"]["run_id"]
        metrics = sql(
            conn, "SELECT metrics FROM provenance.ingestion_run WHERE id=:run", run=run
        ).scalar_one()
        if (
            metrics.get("read") != OWNER_ROWS
            or not metrics.get("accepted")
            or manifest.mapping_version != "2"
            or manifest.workbook_patterns != [OWNER]
            or manifest.worksheets != [SHEET]
            or FIELD not in manifest.known_columns
        ):
            raise SnapshotError(
                "expected the reviewed, privately published ownership snapshot"
            )
        payload = retained_owner_book(root)
        return {
            **_index_rows(conn, run, gis_run, situs_rows(payload), metrics),
            "run_id": str(run),
            "gis_run_id": str(gis_run),
            "workbook_sha256": OWNER_SHA,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    if sys.argv[1:] not in ([], ["--help"], ["-h"]):
        parser.error("the situs index accepts no arguments")
    parser.parse_args()
    try:
        print(json.dumps(index_situs(), indent=2))
    # Database and parser diagnostics can contain private cell contents.
    except Exception as exc:  # noqa: BLE001
        sys.exit(
            f"Private situs index failed ({type(exc).__name__}). Transaction rolled back."
        )
