"""First-publication SQL checks against a disposable migrated PostGIS database."""

import json
import os
from hashlib import sha256
from importlib.resources import files
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration


def test_private_parcel_and_assessor_first_publications():
    url = os.environ.get("CRE_INGEST_TEST_URL")
    if not url:
        pytest.skip("requires a disposable migrated PostGIS database")
    polygon = json.dumps(
        {
            "type": "Polygon",
            "coordinates": [[[-84, 34], [-84, 35], [-83, 35], [-84, 34]]],
        }
    )
    sql = files("cre.ingestion").joinpath("bootstrap_parcels.sql").read_text()
    with (
        psycopg.connect(url.replace("postgresql+psycopg:", "postgresql:")) as conn,
        conn.transaction(force_rollback=True),
    ):
        county = conn.execute(
            """INSERT INTO core.jurisdiction(county_fips, county_name, state_code)
            SELECT n::text, 'Synthetic', 'GA' FROM generate_series(80000, 99999) n
            WHERE NOT EXISTS (SELECT FROM core.jurisdiction j WHERE j.county_fips=n::text)
            LIMIT 1 RETURNING id, county_fips"""
        ).fetchone()
        key = "synthetic_" + uuid4().hex
        source = conn.execute(
            """INSERT INTO provenance.source_system(source_key,publisher)
            VALUES (%s,'Fixture') RETURNING id""",
            (key,),
        ).fetchone()[0]
        dataset = conn.execute(
            """INSERT INTO provenance.source_dataset
            (source_system_id,dataset_key,manifest,enabled,shared_display,export_allowed)
            VALUES (%s,%s,%s,true,false,false) RETURNING id""",
            (source, key, Jsonb({"kind": "parcels", "county_fips": county[1]})),
        ).fetchone()[0]
        attempt = conn.execute(
            """INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on)
            VALUES (%s,'manual','staging',current_date) RETURNING id""",
            (dataset,),
        ).fetchone()[0]
        run = conn.execute(
            """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,
            manifest,observed_on,raw_object_key,artifact_sha256,metrics)
            VALUES (%s,'test','1','{}',current_date,'fixture','test','{}') RETURNING id""",
            (dataset,),
        ).fetchone()[0]
        columns = {
            "address": "ADDRESS",
            "deeded_acres": "DEED",
            "gis_acres": "CALC",
        }
        conn.execute(
            """CREATE TEMP TABLE batch (run_id uuid,attempt_id uuid,dataset_id uuid,
            jurisdiction_id uuid,observed date,columns jsonb) ON COMMIT DROP"""
        )
        conn.execute(
            "INSERT INTO batch VALUES (%s,%s,%s,%s,current_date,%s)",
            (run, attempt, dataset, county[0], Jsonb(columns)),
        )
        conn.execute(
            """CREATE TEMP TABLE incoming_parcel(ordinal bigint, record_id uuid,
            ext_id text, digest text, loc jsonb, pin text, taxpin text, lrsn text,
            gid text, address text, deeded numeric, acres numeric, geometry_json text,
            srid integer, reason text) ON COMMIT DROP"""
        )
        projected = conn.execute(
            "SELECT ST_AsGeoJSON(ST_Transform(ST_GeomFromGeoJSON(%s),2240),12)",
            (polygon,),
        ).fetchone()[0]
        cases = [
            ("00-1 A", "Key 1", polygon, 4326),
            ("002", "Key-2", projected, 2240),
            ("003", "  ", "bad encoding", 4326),
            ("004", None, polygon.replace("-84", "-184"), 4326),
            ("005", None, '{"type":"Point","coordinates":[1,2]}', 4326),
            ("006", None, polygon, 999999),
            ("00-7", None, polygon, 4326),
            (" 00 7", None, polygon, 4326),
            ("008", "DUPLICATE", polygon, 4326),
            ("009", "\tduplicate ", polygon, 4326),
            ("   ", None, polygon, 4326),
            (
                "011",
                None,
                '{"type":"Polygon","coordinates":[[[0,0],[1,1],[0,1],[1,0],[0,0]]]}',
                4326,
            ),
        ]
        with conn.cursor().copy("COPY incoming_parcel FROM STDIN") as copy:
            for n, (pin, taxpin, shape, srid) in enumerate(cases):
                copy.write_row(
                    (
                        n,
                        uuid4(),
                        str(n),
                        sha256(str(n).encode()).hexdigest(),
                        Jsonb({"feature": n}),
                        pin,
                        taxpin,
                        None if n == 1 else str(n),
                        None,
                        "  10   Test Rd ",
                        0,
                        1.25,
                        shape,
                        srid,
                        None,
                    )
                )
        conn.execute(sql)
        assert conn.execute("SELECT * FROM batch_counts").fetchone() == (
            12,
            2,
            10,
            0,
            4,
        )
        assert conn.execute(
            "SELECT count(*) FROM provenance.source_record WHERE run_id=%s", (run,)
        ).fetchone() == (12,)
        assert conn.execute(
            "SELECT count(source_record_id) FROM staging.review_item WHERE attempt_id=%s",
            (attempt,),
        ).fetchone() == (10,)
        assert conn.execute(
            """SELECT p.primary_pin, p.normalized_pin, ST_SRID(g.geom), ST_IsValid(g.geom),
                      a.normalized_address
            FROM core.parcel p JOIN core.parcel_geometry_version g ON g.parcel_id=p.id
            JOIN core.address a ON a.parcel_id=p.id WHERE p.jurisdiction_id=%s ORDER BY p.normalized_pin""",
            (county[0],),
        ).fetchall() == [
            ("00-1 A", "001A", 4326, True, "10 TEST RD"),
            ("002", "002", 4326, True, "10 TEST RD"),
        ]
        assert conn.execute(
            """SELECT c.predicate, c.value->'value', s.locator->>'field' FROM evidence.claim c
            JOIN evidence.claim_support s ON s.claim_id=c.id
            JOIN provenance.source_record r ON r.id=s.source_record_id
            WHERE r.run_id=%s AND s.locator->>'feature'='0' ORDER BY c.predicate""",
            (run,),
        ).fetchall() == [
            ("address", "  10   Test Rd ", "ADDRESS"),
            ("deeded_acres", 0, "DEED"),
            ("gis_acres", 1.25, "CALC"),
        ]
        assert conn.execute(
            "SELECT count(*) FROM core.visible_parcel WHERE dataset_key=%s", (key,)
        ).fetchone() == (0,)
        with (
            pytest.raises(psycopg.errors.RaiseException, match="empty county"),
            conn.transaction(),
        ):
            conn.execute(sql)
        check_assessor_publication(conn, source, key, county[1])


def check_assessor_publication(conn, source, parcel_key, fips):
    assessor_key = parcel_key + "_assessor"
    dataset = conn.execute(
        """INSERT INTO provenance.source_dataset
        (source_system_id,dataset_key,manifest,enabled,shared_display,export_allowed)
        VALUES (%s,%s,%s,true,false,false) RETURNING id""",
        (
            source,
            assessor_key,
            Jsonb(
                {
                    "kind": "assessor",
                    "county_fips": fips,
                    "join_dataset": parcel_key,
                    "join_identifier": "taxpin",
                }
            ),
        ),
    ).fetchone()[0]
    attempt = conn.execute(
        """INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on)
        VALUES (%s,'manual','staging',current_date) RETURNING id""",
        (dataset,),
    ).fetchone()[0]
    run = conn.execute(
        """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,
        manifest,observed_on,raw_object_key,artifact_sha256,metrics)
        VALUES (%s,'test','1','{}',current_date,'fixture','test','{}') RETURNING id""",
        (dataset,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO provenance.ingestion_run(dataset_id,input_fingerprint,mapping_version,
        manifest,observed_on,raw_object_key,artifact_sha256,metrics)
        VALUES (%s,'all_held','1','{}',current_date,'held','held','{"accepted":0}')""",
        (dataset,),
    )
    columns = {
        "owner": "OWNERNAME1",
        "owner_line_2": "OWNERNAME2",
        "mailing_zip": "OWNERZIP",
        "source_total_value": "TOTVAL1",
    }
    conn.execute("DROP TABLE pg_temp.batch_counts")
    conn.execute(
        "UPDATE batch SET dataset_id=%s, attempt_id=%s, run_id=%s, columns=%s",
        (dataset, attempt, run, Jsonb(columns)),
    )
    conn.execute(
        """CREATE TEMP TABLE incoming_assessor(ordinal bigint,record_id uuid,ext_id text,digest text,
        loc jsonb,pin text,lrsn text,owner text,details jsonb,reason text) ON COMMIT DROP"""
    )
    sql = files("cre.ingestion").joinpath("bootstrap_assessor.sql").read_text()
    for inputs, counts in [
        (
            [
                (" key 1 ", None),
                ("KEY-2", "321"),
                ("LRSN_ONLY", "0"),
                ("KEY2", None),
                (" DUP", None),
                ("dup ", None),
                ("A", "789"),
                ("B", "789"),
            ],
            (8, 2, 6, 2, 4),
        ),
        ([("KEY 1", "987"), ("KEY-2", "0")], (2, 0, 2, 0, 2)),
    ]:
        with conn.transaction(force_rollback=True):
            with conn.cursor().copy("COPY incoming_assessor FROM STDIN") as copy:
                for n, (pin, lrsn) in enumerate(inputs):
                    copy.write_row(
                        (
                            n,
                            uuid4(),
                            pin,
                            sha256(pin.encode()).hexdigest(),
                            Jsonb({"sheet": "fixture", "row": n + 2}),
                            pin,
                            lrsn,
                            "Fixture Holdings LLC",
                            Jsonb(
                                {
                                    "owner_line_2": "ATTN FIXTURE",
                                    "mailing_zip": "00123",
                                    "source_total_value": 0,
                                }
                            ),
                            None,
                        )
                    )
            conn.execute(sql)
            assert conn.execute("SELECT * FROM batch_counts").fetchone() == counts
            assert conn.execute(
                "SELECT count(*) FROM provenance.source_record WHERE run_id=%s", (run,)
            ).fetchone() == (counts[0],)
            if counts[1]:
                assert conn.execute(
                    """SELECT count(DISTINCT o.party_id) FROM core.ownership_record o
                    JOIN evidence.claim_support s ON s.claim_id=o.claim_id JOIN provenance.source_record r
                    ON r.id=s.source_record_id JOIN core.party p ON p.id=o.party_id
                    WHERE r.run_id=%s AND p.party_type='organization'""",
                    (run,),
                ).fetchone() == (2,)
                assert conn.execute(
                    """SELECT c.predicate,c.value->'value',s.locator->>'field'
                    FROM evidence.claim c JOIN evidence.claim_support s ON s.claim_id=c.id
                    JOIN provenance.source_record r ON r.id=s.source_record_id WHERE r.run_id=%s
                    AND s.locator->>'row'='2' ORDER BY c.predicate""",
                    (run,),
                ).fetchall() == [
                    ("assessor_listed_owner", "Fixture Holdings LLC", "OWNERNAME1"),
                    ("mailing_zip", "00123", "OWNERZIP"),
                    ("owner_line_2", "ATTN FIXTURE", "OWNERNAME2"),
                    ("source_total_value", 0, "TOTVAL1"),
                ]
                assert conn.execute(
                    "SELECT count(*) FROM evidence.visible_claim WHERE dataset_key=%s",
                    (assessor_key,),
                ).fetchone() == (0,)
            else:
                assert {
                    r[0]
                    for r in conn.execute(
                        "SELECT reason FROM staging.review_item WHERE attempt_id=%s",
                        (attempt,),
                    )
                } == {
                    "assessor LRSNum differs from matched GIS parcel LRSN",
                    "assessor PIN and LRSNum identify different GIS parcels",
                }
