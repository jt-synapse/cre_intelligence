import json
import os
import subprocess
import sys
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine

from cre.ingestion.contract import SnapshotError
from cre.ingestion.service import sql


def owner_book(situs_header="PROPERTYSTREET"):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    stream = BytesIO()
    with ZipFile(stream, "w") as book:
        strings = [
            "PIN",
            situs_header,
            "OWNERADDRESS1",
            "001 A-1",
            " 1 Mixed St  ",
            "Mailing Only",
            "001 A-2",
            "001 A-3",
        ]
        book.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}">'
            + "".join(f"<si><t>{s}</t></si>" for s in strings)
            + "</sst>",
        )
        book.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
            '<c r="C1" t="s"><v>2</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2" t="s"><v>4</v></c>'
            '<c r="C2" t="s"><v>5</v></c></row>'
            '<row r="3"><c r="A3" t="s"><v>6</v></c><c r="C3" t="s"><v>5</v></c></row>'
            '<row r="4"><c r="A4" t="s"><v>7</v></c><c r="B4"><v>1234</v></c></row>'
            "</sheetData></worksheet>",
        )
    return stream.getvalue()


def test_index_reads_physical_rows_original_situs_and_no_mailing_fallback():
    from cre.ingestion.gwinnett_situs import situs_rows

    assert list(situs_rows(owner_book())) == [
        (2, "001 A-1", " 1 Mixed St  "),
        (3, "001 A-2", None),
        (4, "001 A-3", "1234"),
    ]


def test_index_stops_when_situs_field_missing():
    from cre.ingestion.gwinnett_situs import situs_rows

    with pytest.raises(SnapshotError):
        list(situs_rows(owner_book("Unknown Street")))


@pytest.mark.parametrize(("args", "code"), [(["--help"], 0), (["unexpected"], 2)])
def test_cli_handles_arguments_before_opening_index(args, code):
    result = subprocess.run(
        [sys.executable, "-m", "cre.ingestion.gwinnett_situs", *args],
        env={**os.environ, "DATABASE_URL": "sqlite://"},
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == code
    assert "usage:" in result.stdout + result.stderr


@pytest.mark.integration
def test_accepted_situs_replay_and_incomplete_provenance():
    """The held parcel has a populated situs and the accepted blank has a mailing address."""
    from cre.ingestion.gwinnett_companions import OWNER, SHEET
    from cre.ingestion.gwinnett_situs import _index_rows

    url = os.getenv("CRE_INGEST_TEST_URL")
    if not url:
        pytest.skip("requires a migrated disposable PostGIS database")
    eng = create_engine(url)
    with eng.connect() as conn, conn.begin():
        assert sql(conn, "SELECT current_database()").scalar_one().endswith("_test")
        token = uuid4().hex
        run = sql(
            conn,
            """WITH source AS (
            INSERT INTO provenance.source_system(source_key,publisher) VALUES (:token,'Fixture') RETURNING id),
            dataset AS (INSERT INTO provenance.source_dataset(source_system_id,dataset_key,manifest,
            enabled,shared_display,export_allowed) SELECT id,:token,'{}',true,false,false FROM source RETURNING id)
            INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,manifest,
            observed_on,raw_object_key,artifact_sha256,metrics)
            SELECT id,'fixture','2','{}',current_date,'fixture','fixture','{}' FROM dataset RETURNING id""",
            token=token,
        ).scalar_one()
        gis_run = sql(
            conn,
            """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,
            manifest,observed_on,raw_object_key,artifact_sha256,metrics)
            SELECT dataset_id,'fixture_geometry','2','{}',current_date,'gis_fixture','gis_fixture','{}'
            FROM provenance.ingestion_run WHERE id=:run RETURNING id""",
            run=run,
        ).scalar_one()
        attempt = sql(
            conn,
            """INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on,run_id)
            SELECT dataset_id,'manual','published',current_date,id FROM provenance.ingestion_run
            WHERE id=:run RETURNING id""",
            run=run,
        ).scalar_one()
        county = sql(
            conn,
            """INSERT INTO core.jurisdiction(county_fips,county_name,state_code)
            VALUES ('13135','Gwinnett','GA') ON CONFLICT(county_fips) DO UPDATE SET county_name='Gwinnett'
            RETURNING id""",
        ).scalar_one()
        rows = [
            (2, "fixture-a", " 1 Mixed St  "),
            (3, "fixture-b", None),
            (4, "fixture-c", "Held St"),
        ]
        for n, pin, _ in rows:
            loc = {"workbook": OWNER, "sheet": SHEET, "row": n}
            src = sql(
                conn,
                """INSERT INTO provenance.source_record(run_id,external_record_id,content_sha256,locator)
                VALUES (:run,:pin,repeat('1',64),CAST(:loc AS jsonb)) RETURNING id""",
                run=run,
                pin=pin,
                loc=json.dumps(loc),
            ).scalar_one()
            if n == 4:
                sql(
                    conn,
                    """INSERT INTO staging.review_item(attempt_id,source_record_id,reason,locator)
                    VALUES (:attempt,:src,'unmatched',CAST(:loc AS jsonb))""",
                    attempt=attempt,
                    src=src,
                    loc=json.dumps(loc),
                )
                continue
            sql(
                conn,
                """WITH parcel AS (
                INSERT INTO core.parcel(jurisdiction_id,primary_pin,normalized_pin)
                VALUES (:county,:pin,:pin) RETURNING id),
                gis_source AS (INSERT INTO provenance.source_record(run_id,external_record_id,content_sha256,locator)
                VALUES (:gis,:pin,repeat('2',64),'{}') RETURNING id),
                geometry AS (INSERT INTO core.parcel_geometry_version(parcel_id,source_record_id,geom,
                observed_at,is_current,primary_pin,normalized_pin)
                SELECT parcel.id,gis_source.id,ST_Multi(ST_MakeEnvelope(-84,33,-83.9,33.1,4326)),
                current_date,true,:pin,:pin FROM parcel,gis_source),
                party AS (INSERT INTO core.party(party_type,canonical_name)
                VALUES ('unknown','Fixture') RETURNING id),
                claim AS (INSERT INTO evidence.claim(subject_id,subject_type,predicate,value,verification_state,
                observed_at,extraction_method) SELECT id,'parcel','assessor_listed_owner','{}','verified',
                current_date,'direct_mapping' FROM parcel RETURNING id),
                support AS (INSERT INTO evidence.claim_support(claim_id,source_record_id,locator)
                SELECT id,:src, CAST(:loc AS jsonb) FROM claim)
                INSERT INTO core.ownership_record(parcel_id,party_id,ownership_kind,claim_id,observed_on)
                SELECT parcel.id,party.id,'assessor_listed_owner',claim.id,current_date FROM parcel,party,claim""",
                county=county,
                gis=gis_run,
                pin=pin,
                src=src,
                loc=json.dumps({**loc, "field": "OWNERNAME1"}),
            )
        metrics = {"read": 3, "accepted": 2, "quarantined": 1}
        for status in ("indexed", "replayed"):
            assert _index_rows(conn, run, gis_run, rows, metrics) == {
                "status": status,
                "source_rows": 3,
                "accepted_rows": 2,
                "indexed_addresses": 1,
                "accepted_without_address": 1,
            }
            assert sql(
                conn,
                """SELECT s.external_record_id, a.raw_address, a.source_field
                FROM staging.gwinnett_situs_address a JOIN provenance.source_record s
                ON s.id=a.source_record_id""",
            ).all() == [("fixture-a", " 1 Mixed St  ", "PROPERTYSTREET")]
        with pytest.raises(SnapshotError), conn.begin_nested():
            _index_rows(
                conn, run, gis_run, [*rows[:2], (4, "wrong-pin", "Held St")], metrics
            )
        with pytest.raises(SnapshotError), conn.begin_nested():
            _index_rows(conn, run, uuid4(), rows, metrics)
        conn.rollback()


def test_private_identity_roll_preserves_taxpin_lrsn_street_and_excel_row():
    from cre.ingestion.gwinnett_situs import identity_roll

    # The fixture's third field stands in for the county LRSNum column.
    source = BytesIO()
    with ZipFile(BytesIO(owner_book())) as original, ZipFile(source, "w") as new:
        for name in original.namelist():
            payload = original.read(name)
            if name == "xl/sharedStrings.xml":
                payload = payload.replace(b"OWNERADDRESS1", b"LRSNum").replace(
                    b"Mailing Only", b"300"
                )
            if name.endswith("sheet1.xml"):
                payload = payload.replace(b'r="C3" t="s"><v>5', b'r="C3"><v>301')
                payload = payload.replace(
                    b"<v>1234</v></c></row>",
                    b'<v>1234</v></c><c r="C4"><v>302</v></c></row>',
                )
            new.writestr(name, payload)
    assert identity_roll(source.getvalue(), expected_rows=3) == {
        "001 A-1": (2, "001 A-1", "300", " 1 Mixed St  "),
        "001 A-2": (3, "001 A-2", "301", ""),
        "001 A-3": (4, "001 A-3", "302", "1234"),
    }
    with pytest.raises(SnapshotError, match="row count"):
        identity_roll(source.getvalue(), expected_rows=4)
