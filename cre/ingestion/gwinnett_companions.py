"""Index reviewed companion worksheets in the retained private Gwinnett assessor ZIP."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4
from xml.etree.ElementTree import iterparse
from zipfile import ZipFile

from openpyxl.reader.strings import read_string_table
from psycopg.types.json import Jsonb

from cre.db import engine
from cre.ingestion.contract import SnapshotError, _open_book, _scalar
from cre.ingestion.gwinnett_bootstrap import private_objects, private_policy
from cre.ingestion.service import sql

ARCHIVE_SHA = "e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca"
FOLDER = "tax_assessor_property_ownership_data/"
OWNER = FOLDER + "2026 Property Ownership.xlsx"
SHEET = "Sheet1"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass(frozen=True)
class Book:
    filename: str
    columns: int
    rows: int
    matched: int = 0
    reference: bool = False


BOOKS = (
    Book("CamaFull_Improv.xlsx", 82, 308830, 305803),
    Book("CamaFull_Land.xlsx", 107, 323701, 315343),
    Book("Property Class Code List 2026.xlsx", 6, 284, reference=True),
    Book("TAX DIGEST OWNERSHIP LAYOUT.xlsx", 5, 42, reference=True),
)

DDL = """
CREATE TABLE IF NOT EXISTS staging.gwinnett_companion_workbook (
    id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES provenance.ingestion_run(id),
    workbook text NOT NULL, member_sha256 text NOT NULL, sheet text NOT NULL,
    headers jsonb NOT NULL CHECK(jsonb_typeof(headers)='array'),
    reference_table boolean NOT NULL, UNIQUE(run_id,workbook,sheet)
);
CREATE TABLE IF NOT EXISTS staging.gwinnett_companion_row (
    workbook_id uuid NOT NULL REFERENCES staging.gwinnett_companion_workbook(id),
    excel_row integer NOT NULL CHECK(excel_row>1),
    source_pin text, source_lrsn bigint,
    ownership_source_record_id uuid REFERENCES provenance.source_record(id),
    reference_cells jsonb,
    CHECK ((source_pin IS NOT NULL AND source_lrsn IS NOT NULL AND reference_cells IS NULL)
        OR (source_pin IS NULL AND source_lrsn IS NULL AND ownership_source_record_id IS NULL
            AND reference_cells IS NOT NULL AND jsonb_typeof(reference_cells)='array')),
    PRIMARY KEY(workbook_id,excel_row)
);
CREATE INDEX IF NOT EXISTS gwinnett_companion_owner ON staging.gwinnett_companion_row(ownership_source_record_id)
    WHERE ownership_source_record_id IS NOT NULL;
"""


def _literal(cell, strings):
    value = cell.findtext(NS + "v")
    if value is None:
        return None
    return strings[int(value)] if cell.get("t") == "s" else value


def _rows(stream):
    """Yield complete physical worksheet rows, releasing processed XML elements."""
    sheet_data = None
    for event, item in iterparse(stream, events=("start", "end")):
        if event == "start" and item.tag == NS + "sheetData":
            sheet_data = item
        elif event == "end" and item.tag == NS + "row":
            yield int(item.attrib["r"]), item
            if sheet_data is not None:
                sheet_data.remove(item)


@contextmanager
def source_keys(payload, width, *, corroborate):
    # Only called on a byte-verified, fixed release with one reviewed worksheet per file.
    with ZipFile(BytesIO(payload)) as book:
        with book.open("xl/sharedStrings.xml") as stream:
            strings = read_string_table(stream)
        with book.open("xl/worksheets/sheet1.xml") as stream:
            rows = _rows(stream)
            n, header = next(rows)
            names = [_literal(c, strings) for c in header]
            if n != 1 or len(names) != width or len(set(names)) != width:
                raise SnapshotError("unexpected companion worksheet header")
            needed = {"PIN", "LRSNum", "LRSN"} if corroborate else {"PIN", "LRSNum"}
            columns = {
                cell.attrib["r"][:-1]: name
                for cell, name in zip(header, names)
                if name in needed
            }
            if set(columns.values()) != needed:
                raise SnapshotError("unreviewed companion source keys")

            def keys():
                for row_num, row in rows:
                    values = {}
                    for cell in row:
                        column = columns.get(cell.attrib["r"].rstrip("0123456789"))
                        if column:
                            values[column] = _literal(cell, strings)
                    pin, lrsn = values.get("PIN"), values.get("LRSNum")
                    if not pin or not lrsn or not lrsn.isdecimal():
                        raise SnapshotError("missing or invalid companion source key")
                    if corroborate and values.get("LRSN") != lrsn:
                        raise SnapshotError("inconsistent source LRSNum and LRSN")
                    yield row_num, pin, int(lrsn)

            yield names, keys()


def prepare_owner(conn, archive, run):
    sql(
        conn,
        """CREATE TEMP TABLE raw_owner_keys(
        excel_row integer PRIMARY KEY, pin text NOT NULL UNIQUE, lrsn bigint NOT NULL UNIQUE
    ) ON COMMIT DROP""",
    )
    db = conn.connection.driver_connection
    count = 0
    with (
        source_keys(archive.read(OWNER), 42, corroborate=False) as (_, rows),
        db.cursor() as cur,
        cur.copy("COPY raw_owner_keys FROM STDIN") as out,
    ):
        for row in rows:
            out.write_row(row)
            count += 1
    if count != 315343:
        raise SnapshotError(
            "ownership workbook row count differs from reviewed release"
        )
    sql(conn, "ANALYZE raw_owner_keys")
    sql(
        conn,
        """CREATE TEMP TABLE companion_owner ON COMMIT DROP AS
        SELECT o.pin,o.lrsn,s.id FROM raw_owner_keys o JOIN provenance.source_record s
          ON s.external_record_id=o.pin AND s.locator->>'row'=o.excel_row::text
        WHERE s.run_id=:run AND s.locator->>'sheet'=:sheet AND s.locator->>'workbook'=:owner""",
        run=run,
        sheet=SHEET,
        owner=OWNER,
    )
    sql(conn, "CREATE UNIQUE INDEX ON companion_owner(pin,lrsn)")
    if sql(conn, "SELECT count(*) FROM companion_owner").scalar_one() != count:
        raise SnapshotError("ownership source-record linkage failed")
    sql(conn, "ANALYZE companion_owner")


def index_book(conn, archive, run, spec):
    name = FOLDER + spec.filename
    payload = archive.read(name)
    workbook_id = uuid4()
    db = conn.connection.driver_connection

    def register(headers):
        if len(headers) != spec.columns:
            raise SnapshotError("unexpected companion field count")
        sql(
            conn,
            """INSERT INTO staging.gwinnett_companion_workbook
          (id,run_id,workbook,member_sha256,sheet,headers,reference_table) VALUES
          (:id,:run,:name,:digest,:sheet,CAST(:headers AS jsonb),:ref)""",
            id=workbook_id,
            run=run,
            name=name,
            digest=hashlib.sha256(payload).hexdigest(),
            sheet=SHEET,
            headers=json.dumps(headers),
            ref=spec.reference,
        )

    count = 0
    if spec.reference:
        book = _open_book(payload)
        try:
            if book.sheetnames != [SHEET]:
                raise SnapshotError("unexpected reference worksheet")
            rows = iter(book[SHEET].values)
            register(list(next(rows)))
            with (
                db.cursor() as cur,
                cur.copy(
                    "COPY staging.gwinnett_companion_row(workbook_id,excel_row,reference_cells) FROM STDIN"
                ) as out,
            ):
                for row_num, values in enumerate(rows, 2):
                    if any(v is not None for v in values):
                        out.write_row(
                            (workbook_id, row_num, Jsonb([_scalar(v) for v in values]))
                        )
                        count += 1
        finally:
            book.close()
    else:
        sql(conn, "TRUNCATE companion_keys")
        with source_keys(payload, spec.columns, corroborate=True) as (headers, rows):
            register(headers)
            with db.cursor() as cur, cur.copy("COPY companion_keys FROM STDIN") as out:
                for row in rows:
                    out.write_row(row)
                    count += 1
        sql(conn, "ANALYZE companion_keys")
        sql(
            conn,
            """INSERT INTO staging.gwinnett_companion_row
           (workbook_id,excel_row,source_pin,source_lrsn,ownership_source_record_id)
           SELECT :w,k.excel_row,k.pin,k.lrsn,o.id FROM companion_keys k
           LEFT JOIN companion_owner o ON o.pin=k.pin AND o.lrsn=k.lrsn""",
            w=workbook_id,
        )
    if count != spec.rows:
        raise SnapshotError(
            "companion worksheet count differs from the inspected release"
        )
    print(
        f"{spec.filename}: indexed {count:,} source rows", file=sys.stderr, flush=True
    )


def summary(conn, run):
    rows = sql(
        conn,
        """SELECT w.workbook, count(*) AS rows, count(r.ownership_source_record_id) AS linked,
        count(DISTINCT r.ownership_source_record_id) AS distinct_ownership_source_rows,
        count(r.reference_cells) AS reference_rows,
        min(r.excel_row) AS first_excel_row, max(r.excel_row) AS last_excel_row,
        jsonb_array_length(w.headers) AS source_columns,
        count(*) FILTER (WHERE w.reference_table <> (r.reference_cells IS NOT NULL)
          OR jsonb_array_length(r.reference_cells) <> jsonb_array_length(w.headers)
          OR (r.ownership_source_record_id IS NOT NULL AND
            (s.run_id IS DISTINCT FROM w.run_id OR s.external_record_id IS DISTINCT FROM r.source_pin
               OR s.locator->>'workbook' IS DISTINCT FROM :owner
               OR s.locator->>'sheet' IS DISTINCT FROM :sheet))) AS invalid_links_or_references
        FROM staging.gwinnett_companion_workbook w JOIN staging.gwinnett_companion_row r ON r.workbook_id=w.id
        LEFT JOIN provenance.source_record s ON s.id=r.ownership_source_record_id
        WHERE w.run_id=:run AND w.sheet=:sheet GROUP BY w.id ORDER BY w.workbook""",
        run=run,
        owner=OWNER,
        sheet=SHEET,
    ).mappings()
    rows = {r["workbook"]: dict(r) for r in rows}
    for spec in BOOKS:
        r = rows.get(FOLDER + spec.filename)
        if (
            not r
            or r["rows"] != spec.rows
            or r["source_columns"] != spec.columns
            or r["first_excel_row"] != 2
            or r["last_excel_row"] != spec.rows + 1
            or r["invalid_links_or_references"] != 0
            or r["linked"] != spec.matched
            or r["reference_rows"] != (spec.rows if spec.reference else 0)
        ):
            raise SnapshotError("companion counts differ from the reviewed archive")
    if len(rows) != len(BOOKS):
        raise SnapshotError("unexpected companion workbook")
    return list(rows.values())


def index_companions():
    root = private_objects()
    with engine().begin() as conn:
        ds, manifest = private_policy(conn, "gwinnett_assessor")
        sql(conn, "SELECT pg_advisory_xact_lock(174274,13135)")
        run = sql(
            conn,
            """SELECT r.id FROM provenance.ingestion_run r JOIN provenance.source_dataset d
          ON d.id=r.dataset_id WHERE r.dataset_id=:ds AND d.enabled AND NOT d.shared_display AND NOT d.export_allowed
          AND r.raw_object_key=:sha AND r.artifact_sha256=:sha AND r.mapping_version=:v
          AND (r.metrics->>'accepted')::bigint > 0""",
            ds=ds,
            sha=ARCHIVE_SHA,
            v=manifest.mapping_version,
        ).scalar_one_or_none()
        if not run or set(manifest.archive_companions) != {
            FOLDER + b.filename for b in BOOKS
        }:
            raise SnapshotError(
                "publish the reviewed ownership workbook in the private database first"
            )
        path = root / ARCHIVE_SHA[:2] / ARCHIVE_SHA
        if path.resolve() != path or not path.is_file():
            raise SnapshotError("expected the private retained county archive")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA:
                raise SnapshotError(
                    "retained ZIP digest differs from the reviewed release"
                )
            with conn.connection.driver_connection.cursor() as cur:
                cur.execute(DDL, prepare=False)
            exists = sql(
                conn,
                "SELECT EXISTS(SELECT FROM staging.gwinnett_companion_workbook WHERE run_id=:r)",
                r=run,
            ).scalar_one()
            if not exists:
                sql(
                    conn,
                    "CREATE TEMP TABLE companion_keys(excel_row integer PRIMARY KEY,pin text,lrsn bigint) ON COMMIT DROP",
                )
                stream.seek(0)
                with ZipFile(stream) as archive:
                    names = [i.filename for i in archive.infolist() if not i.is_dir()]
                    if sorted(names) != sorted([OWNER, *manifest.archive_companions]):
                        raise SnapshotError("source archive contents changed")
                    prepare_owner(conn, archive, run)
                    for spec in BOOKS:
                        index_book(conn, archive, run, spec)
            return {
                "status": "replayed" if exists else "indexed",
                "run_id": str(run),
                "workbooks": summary(conn, run),
            }


if __name__ == "__main__":
    try:
        print(json.dumps(index_companions(), indent=2))
    except Exception as exc:  # noqa: BLE001 -- CLI must redact errors containing source rows.
        # Database driver errors may contain private source rows.
        if isinstance(exc, (SnapshotError, PermissionError)):
            sys.exit(str(exc))
        sys.exit(
            f"Companion index failed ({type(exc).__name__}); transaction rolled back."
        )
