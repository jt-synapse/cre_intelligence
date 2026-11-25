"""Run against a migrated, disposable PostGIS database via CRE_INGEST_TEST_URL."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from test_ingestion_contract import manifest

from cre import storage
from cre.db import engine
from cre.ingestion import service
from cre.ingestion.contract import SnapshotError
from cre.ingestion.demo import assessor_bytes, parcel_bytes

pytestmark = pytest.mark.integration
DAY = date(2026, 1, 1)


@pytest.fixture
def sources(monkeypatch, tmp_path):
    url = os.environ.get("CRE_INGEST_TEST_URL")
    if not url:
        pytest.skip(
            "CRE_INGEST_TEST_URL requires a disposable migrated PostGIS database"
        )
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CRE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("CRE_S3_BUCKET", raising=False)
    token = uuid4().hex
    with engine().begin() as conn:
        fips = service.sql(
            conn,
            """SELECT lpad(n::text,5,'0') FROM generate_series(70000,98999) AS n
            WHERE NOT EXISTS (SELECT 1 FROM core.jurisdiction j WHERE j.county_fips=n::text)
            ORDER BY random() LIMIT 1""",
        ).scalar_one()
    result = []
    for name in ("demo_parcels", "demo_assessor"):
        m = manifest(name).model_copy(
            update={"county_fips": fips, "dataset_key": name + "_" + token}
        )
        service.register(m)
        result.append(m)
    try:
        yield result
    finally:
        # A reused test database also serves Explorer tests with these fictional PINs.
        for source in result:
            source.rights.status = "disabled"
            service.register(source)


def records(query, **params):
    with engine().connect() as conn:
        return service.sql(conn, query, **params).mappings().all()


def features(count=3):
    return json.loads(parcel_bytes(count))


def pack(obj):
    return json.dumps(obj).encode()


def test_concurrent_replay_and_lineage(sources):
    parcel, _ = sources
    data = parcel_bytes()
    with ThreadPoolExecutor(2) as workers:
        runs = list(
            workers.map(
                lambda _: service.import_snapshot(parcel.dataset_key, data, DAY),
                range(2),
            )
        )
    assert sorted(r["status"] for r in runs) == ["published", "replayed"]
    assert len({r["run_id"] for r in runs}) == 1
    assert runs[0]["accepted"] == 3
    obj = features()
    obj["features"].reverse()
    assert (
        service.import_snapshot(parcel.dataset_key, pack(obj), DAY)["status"]
        == "replayed"
    )
    claims = records(
        """SELECT c.*,r.raw_object_key FROM evidence.visible_claim c JOIN provenance.source_record s
        ON s.id=c.source_record_id JOIN provenance.ingestion_run r ON r.id=s.run_id WHERE c.dataset_key=:d""",
        d=parcel.dataset_key,
    )
    assert len(claims) == 9
    for claim in claims:
        feature = json.loads(storage.get_bytes(claim["raw_object_key"]))["features"][
            claim["locator"]["feature"]
        ]
        assert (
            feature["properties"][claim["locator"]["field"]] == claim["value"]["value"]
        )


def test_return_to_prior_geometry_publishes_a_new_dated_version(sources):
    parcel, _ = sources
    original = parcel_bytes(1)
    displaced = features(1)
    for point in displaced["features"][0]["geometry"]["coordinates"][0]:
        point[0] += 0.01
    first = service.import_snapshot(parcel.dataset_key, original, DAY)
    service.import_snapshot(
        parcel.dataset_key, pack(displaced), DAY + timedelta(days=1)
    )
    last_day = DAY + timedelta(days=2)
    returned = service.import_snapshot(parcel.dataset_key, original, last_day)
    assert returned["status"] == "published" and returned["run_id"] != first["run_id"]
    assert returned["changed"] == 1
    versions = records(
        """SELECT g.is_current,s.observed_on,ST_XMin(g.geom) AS west FROM core.parcel_geometry_version g
        JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id
        WHERE s.dataset_key=:dataset ORDER BY s.observed_on""",
        dataset=parcel.dataset_key,
    )
    assert [v["is_current"] for v in versions] == [False, False, True]
    assert [v["west"] for v in versions] == pytest.approx([-84.01, -84.00, -84.01])
    assert versions[-1]["observed_on"] == last_day
    assert (
        service.import_snapshot(parcel.dataset_key, original, last_day)["run_id"]
        == returned["run_id"]
    )


def test_unchanged_new_observation_remains_current_after_a_backfill(sources):
    parcel, _ = sources
    original = parcel_bytes(1)
    service.import_snapshot(parcel.dataset_key, original, DAY)
    latest = DAY + timedelta(days=2)
    service.import_snapshot(parcel.dataset_key, original, latest)
    older = features(1)
    older["features"][0]["properties"]["ADDRESS"] = "Earlier Address"
    service.import_snapshot(parcel.dataset_key, pack(older), DAY + timedelta(days=1))
    visible = records(
        "SELECT address,observed_at FROM core.visible_parcel WHERE dataset_key=:dataset",
        dataset=parcel.dataset_key,
    )
    assert len(visible) == 1
    assert visible[0]["address"] == "100 Example Commerce Dr"
    assert visible[0]["observed_at"].date() == latest


def test_return_to_prior_assessor_owner_preserves_the_new_observation(sources):
    parcel, assessor = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(1), DAY)
    original = assessor_bytes(1)
    service.import_snapshot(assessor.dataset_key, original, DAY)
    book = load_workbook(BytesIO(original))
    book.active["B2"] = "Successor LLC"
    changed = BytesIO()
    book.save(changed)
    service.import_snapshot(
        assessor.dataset_key, changed.getvalue(), DAY + timedelta(days=1)
    )
    service.import_snapshot(assessor.dataset_key, original, DAY + timedelta(days=2))
    claims = records(
        """SELECT value->>'value' AS owner FROM evidence.visible_claim
        WHERE dataset_key=:dataset AND predicate='assessor_listed_owner' ORDER BY observed_at""",
        dataset=assessor.dataset_key,
    )
    assert [c["owner"] for c in claims] == [
        "Example Commerce Holdings LLC",
        "Successor LLC",
        "Example Commerce Holdings LLC",
    ]


def test_retry_recovers_a_legacy_replay_using_its_original_observation_date(sources):
    parcel, _ = sources
    first = service.import_snapshot(parcel.dataset_key, parcel_bytes(1), DAY)
    later = DAY + timedelta(days=7)
    with engine().begin() as conn:
        legacy = service.sql(
            conn,
            """
            INSERT INTO provenance.ingestion_attempt(dataset_id,mode,status,observed_on,run_id,raw_object_key)
            SELECT dataset_id,'manual','replayed',:day,id,raw_object_key FROM provenance.ingestion_run
            WHERE id=:run RETURNING id""",
            day=later,
            run=first["run_id"],
        ).scalar_one()
        review = service.sql(
            conn,
            """INSERT INTO staging.review_item(attempt_id,reason,locator)
            VALUES (:legacy,'retry retained snapshot at its original observation date','{}')
            RETURNING id""",
            legacy=legacy,
        ).scalar_one()
    recovered = service.retry_attempt(str(legacy))
    assert recovered["status"] == "published"
    assert service.retry_attempt(str(legacy))["run_id"] == recovered["run_id"]
    resolution = records(
        "SELECT attempt_id FROM staging.review_resolution WHERE review_item_id=:review",
        review=review,
    )
    assert [str(row["attempt_id"]) for row in resolution] == [recovered["attempt_id"]]
    assert (
        records(
            "SELECT observed_on FROM provenance.ingestion_run WHERE id=:run",
            run=recovered["run_id"],
        )[0]["observed_on"]
        == later
    )


def test_invalid_polygon_stays_out_of_core(sources):
    parcel, _ = sources
    obj = features(1)
    obj["features"][0]["geometry"]["coordinates"] = [
        [[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]
    ]
    run = service.import_snapshot(parcel.dataset_key, pack(obj), DAY)
    assert run["quarantined"] == 1 and run["accepted"] == 0
    assert (
        len(
            records(
                "SELECT * FROM staging.review_item WHERE attempt_id=:a",
                a=run["attempt_id"],
            )
        )
        == 1
    )


def test_changed_geometry_and_partial_snapshot(sources):
    parcel, _ = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(3), DAY)
    obj = features(1)
    ring = obj["features"][0]["geometry"]["coordinates"][0]
    for pt in ring:
        pt[0] += 0.001
    run = service.import_snapshot(
        parcel.dataset_key, pack(obj), DAY + timedelta(days=5)
    )
    assert run["missing_from_snapshot"] == 2
    assert run["changed"] == 1
    geoms = records(
        """SELECT g.is_current,g.primary_pin,ST_IsValid(geom) AS valid
        FROM core.parcel_geometry_version g JOIN provenance.visible_source_record s ON s.source_record_id=g.source_record_id
        WHERE s.dataset_key=:d""",
        d=parcel.dataset_key,
    )
    assert len(geoms) == 4 and sum(g["is_current"] for g in geoms) == 3
    assert all(g["valid"] for g in geoms)
    assert geoms[0]["primary_pin"].startswith("000")


def test_atomic_publication_and_retry(sources, monkeypatch):
    parcel, _ = sources
    original = service._parcel
    checked = []

    def interrupt(*args):
        result = original(*args)
        checked.append(True)
        if len(checked) == 2:
            raise RuntimeError("injected publication interruption")
        return result

    with monkeypatch.context() as m:
        m.setattr(service, "_parcel", interrupt)
        with pytest.raises(RuntimeError, match="injected"):
            service.import_snapshot(parcel.dataset_key, parcel_bytes(), DAY)
    assert not records(
        "SELECT id FROM core.visible_parcel WHERE dataset_key=:d", d=parcel.dataset_key
    )
    attempt = records(
        """SELECT status,raw_object_key FROM provenance.ingestion_attempt a JOIN provenance.source_dataset d
        ON d.id=a.dataset_id WHERE d.dataset_key=:key""",
        key=parcel.dataset_key,
    )[0]
    assert (
        attempt["status"] == "failed"
        and storage.get_bytes(attempt["raw_object_key"]) == parcel_bytes()
    )
    assert (
        service.import_snapshot(parcel.dataset_key, parcel_bytes(), DAY)["new_parcels"]
        == 3
    )


def test_conflicting_owners_and_similar_llcs(sources):
    parcel, assessor = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(), DAY)
    service.import_snapshot(assessor.dataset_key, assessor_bytes(), DAY)
    book = load_workbook(BytesIO(assessor_bytes()))
    book.active["B2"] = "Example Commerce Holdings II LLC"
    out = BytesIO()
    book.save(out)
    run = service.import_snapshot(assessor.dataset_key, out.getvalue(), DAY)
    assert run["conflicting"] == 1
    claims = records(
        """SELECT c.value,c.verification_state,p.primary_pin FROM evidence.visible_claim c
        JOIN core.visible_parcel p ON p.id=c.subject_id WHERE c.dataset_key=:d AND c.predicate='assessor_listed_owner'""",
        d=assessor.dataset_key,
    )
    same = [c for c in claims if c["value"]["value"] == "Example Commerce Holdings LLC"]
    assert len({c["value"]["party_id"] for c in same}) == 2
    assert {
        c["value"]["value"] for c in claims if c["primary_pin"] == "0001 A 001"
    } == {"Example Commerce Holdings LLC", "Example Commerce Holdings II LLC"}
    assert {
        c["verification_state"] for c in claims if c["primary_pin"] == "0001 A 001"
    } == {"conflicted"}


def test_authorization_and_schema_drift(sources):
    parcel, _ = sources
    with pytest.raises(PermissionError):
        service.import_snapshot(
            parcel.dataset_key, parcel_bytes(), DAY, method="automatic"
        )
    obj = features()
    obj["features"][-1]["properties"]["PIN"] = 512
    with pytest.raises(SnapshotError, match="mapping review"):
        service.import_snapshot(parcel.dataset_key, pack(obj), DAY)
    attempts = records(
        """SELECT status,raw_object_key FROM provenance.ingestion_attempt a JOIN provenance.source_dataset d
        ON d.id=a.dataset_id WHERE d.dataset_key=:key ORDER BY started_at""",
        key=parcel.dataset_key,
    )
    assert [a["status"] for a in attempts] == ["blocked", "quarantined"]
    assert attempts[0]["raw_object_key"] is None
    assert not records(
        "SELECT id FROM core.visible_parcel WHERE dataset_key=:d", d=parcel.dataset_key
    )


def test_source_revocation_hides_records_and_claims(sources):
    parcel, _ = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(), DAY)
    parcel.rights.export_allowed = False
    service.register(parcel)
    assert all(
        not c["export_allowed"]
        for c in records(
            "SELECT export_allowed FROM evidence.visible_claim WHERE dataset_key=:d",
            d=parcel.dataset_key,
        )
    )
    parcel.rights.status = "disabled"
    service.register(parcel)
    assert not records(
        "SELECT id FROM core.visible_parcel WHERE dataset_key=:d", d=parcel.dataset_key
    )
    assert not records(
        "SELECT id FROM evidence.visible_claim WHERE dataset_key=:d",
        d=parcel.dataset_key,
    )


def test_assessor_confirmed_alternate_join(sources):
    parcel, assessor = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(), DAY)
    cfg = assessor.model_dump()
    cfg.update(
        mapping_version="2", join_identifier="lrsn", join_dataset=parcel.dataset_key
    )
    alternate = type(assessor).model_validate(cfg)
    service.register(alternate)
    book = load_workbook(BytesIO(assessor_bytes()))
    for n in range(3):
        book.active.cell(row=n + 2, column=1, value=10000 + n)
    out = BytesIO()
    book.save(out)
    assert (
        service.import_snapshot(assessor.dataset_key, out.getvalue(), DAY)[
            "matched_owners"
        ]
        == 3
    )


def test_retry_after_missing_dependency_preserves_old_rows(sources):
    parcel, assessor = sources
    service.import_snapshot(parcel.dataset_key, parcel_bytes(1), DAY)
    first = service.import_snapshot(assessor.dataset_key, assessor_bytes(2), DAY)
    assert first["accepted"] == 1 and first["unmatched"] == 1
    service.import_snapshot(parcel.dataset_key, parcel_bytes(2), DAY)
    repaired = service.retry_attempt(first["attempt_id"])
    assert repaired["accepted"] == 2 and repaired["unmatched"] == 0
    assert repaired["run_id"] == first["run_id"]
    assert service.retry_attempt(first["attempt_id"])["status"] == "replayed"
    claims = records(
        "SELECT id FROM evidence.visible_claim WHERE dataset_key=:d AND predicate='assessor_listed_owner'",
        d=assessor.dataset_key,
    )
    assert len(claims) == 2
    audits = records(
        "SELECT quality FROM provenance.ingestion_attempt WHERE id=:id",
        id=first["attempt_id"],
    )
    assert audits[0]["quality"]["accepted"] == 1


def test_input_file_opened_only_after_authorization(sources):
    parcel, _ = sources

    def must_not_open():
        pytest.fail("attempted to read the file before checking source rights")

    with pytest.raises(PermissionError):
        service.import_snapshot(
            parcel.dataset_key, must_not_open, DAY, method="automatic"
        )


def test_gwinnett_generic_import_blocks_before_reading_the_private_artifact(sources):
    county = manifest("gwinnett_parcels")
    service.register(county)
    with pytest.raises(PermissionError, match="gwinnett-internal"):
        service.import_snapshot(
            county.dataset_key,
            lambda: pytest.fail("generic loader opened the county artifact"),
            DAY,
        )
    attempt = records(
        """SELECT a.status,a.raw_object_key FROM provenance.ingestion_attempt a
        JOIN provenance.source_dataset d ON d.id=a.dataset_id
        WHERE d.dataset_key=:key ORDER BY a.started_at DESC LIMIT 1""",
        key=county.dataset_key,
    )[0]
    assert attempt["status"] == "blocked"
    assert attempt["raw_object_key"] is None


def test_private_bootstrap_recovers_after_every_row_is_held(
    sources, monkeypatch, tmp_path
):
    from cre.ingestion import gwinnett_bootstrap as bootstrap

    source, _ = sources
    source.rights.shared_display = source.rights.export_allowed = False
    service.register(source)
    # Exercise publication and attempts in the disposable, synthetic namespace.
    monkeypatch.setitem(
        bootstrap.COLUMNS, source.dataset_key, bootstrap.COLUMNS["gwinnett_parcels"]
    )
    monkeypatch.setattr(bootstrap, "private_objects", lambda: tmp_path / "objects")
    monkeypatch.setattr(
        bootstrap,
        "private_policy",
        lambda conn, key: service._dataset(conn, key, lock=True),
    )
    parcel = features(1)
    parcel["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
    valid = tmp_path / "valid.geojson"
    valid.write_bytes(pack(parcel))
    parcel["features"][0]["geometry"] = None
    invalid = tmp_path / "invalid.geojson"
    invalid.write_bytes(pack(parcel))

    def load(path, day=DAY):
        return bootstrap.import_private(source.dataset_key, path, day)

    held = load(invalid)
    repeated = load(invalid)
    assert (held["status"], repeated["status"]) == ("quarantined", "quarantined")
    assert held["accepted"] == 0 and held["run_id"] == repeated["run_id"]
    invalid.write_text(json.dumps(parcel, indent=2))
    repackaged = load(invalid)
    assert (
        repackaged["status"] == "quarantined" and repackaged["run_id"] == held["run_id"]
    )
    published = load(valid)
    assert published["status"] == "published" and published["accepted"] == 1
    assert load(valid)["run_id"] == published["run_id"]
    with pytest.raises(SnapshotError, match="different baseline"):
        load(valid, DAY + timedelta(days=1))


def test_private_policy_rechecks_operational_use_flags(sources, monkeypatch):
    from cre.ingestion import gwinnett_bootstrap as bootstrap

    parcel_id = service.register(manifest("gwinnett_parcels"))
    service.register(manifest("gwinnett_assessor"))
    db = engine().url.database
    monkeypatch.setattr(bootstrap, "PRIVATE_DATABASE", db)
    quoted_db = engine().dialect.identifier_preparer.quote(db)
    # Roll back the temporary database ACL and contradictory operational flags.
    with engine().connect() as conn:
        conn.exec_driver_sql(
            f"REVOKE CONNECT ON DATABASE {quoted_db} FROM PUBLIC, cre_runtime, cre_worker"
        )
        bootstrap.private_policy(conn, "gwinnett_assessor")
        for flag, invalid in (
            ("enabled", False),
            ("shared_display", True),
            ("export_allowed", True),
        ):
            with conn.begin_nested() as tx:
                service.sql(
                    conn,
                    f"UPDATE provenance.source_dataset SET {flag}=:value WHERE id=:ds",
                    value=invalid,
                    ds=parcel_id,
                )
                for key in ("gwinnett_parcels", "gwinnett_assessor"):
                    with pytest.raises(
                        PermissionError, match="enabled for private use"
                    ):
                        bootstrap.private_policy(conn, key)
                tx.rollback()


def test_gwinnett_retry_uses_verified_private_object_and_redacts_import_errors(
    sources, monkeypatch, tmp_path
):
    from cre.ingestion import gwinnett_bootstrap

    ds = service.register(manifest("gwinnett_parcels"))
    payload = b"fixture"
    key = sha256(payload).hexdigest()
    path = tmp_path / key[:2] / key
    path.parent.mkdir()
    path.write_bytes(payload)
    with engine().begin() as conn:
        attempt = service.sql(
            conn,
            """INSERT INTO provenance.ingestion_attempt
            (dataset_id,mode,status,observed_on,raw_object_key,artifact_sha256)
            VALUES (:ds,'manual','failed',:day,:key,:key) RETURNING id""",
            ds=ds,
            day=DAY,
            key=key,
        ).scalar_one()
    monkeypatch.setattr(gwinnett_bootstrap, "private_objects", lambda: tmp_path)
    monkeypatch.setattr(gwinnett_bootstrap, "private_policy", lambda conn, key: None)
    calls = []

    def fail_import(dataset, retained, observed):
        calls.append((dataset, retained, observed))
        raise ValueError("fixture-private-row")

    monkeypatch.setattr(gwinnett_bootstrap, "import_private", fail_import)
    with pytest.raises(RuntimeError, match="Private Gwinnett import failed") as error:
        service.retry_attempt(str(attempt))
    assert calls == [("gwinnett_parcels", path, DAY)]
    assert "fixture-private-row" not in str(error.value)
    assert error.value.__suppress_context__
    path.write_bytes(b"unexpected change")
    with pytest.raises(RuntimeError, match="OSError"):
        service.retry_attempt(str(attempt))
    assert len(calls) == 1


def test_field_reader_paired_refresh_and_short_full_snapshot(sources):
    parcels, owners = sources
    for source in sources:
        source.paired_datasets = [parcels.dataset_key, owners.dataset_key]
        source.expected_snapshot_rows = 3
        service.register(source)

    def state():
        return records(
            """
          SELECT v.address,v.geometry_version_id,v.projection_generation_id,o.value->>'value' AS owner
          FROM core.visible_parcel v LEFT JOIN evidence.reader_owner o ON o.subject_id=v.id
          WHERE v.county_fips=:county ORDER BY v.primary_pin""",
            county=parcels.county_fips,
        )

    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)
    assert state() == []
    service.import_snapshot(owners.dataset_key, assessor_bytes(), DAY)
    first = state()
    assert len(first) == 3 and all(r["owner"] for r in first)

    updated = features()
    updated["features"][0]["properties"]["ADDRESS"] = "New field address"
    next_day = DAY + timedelta(days=1)
    service.import_snapshot(parcels.dataset_key, pack(updated), next_day)
    assert state() == first
    with pytest.raises(SnapshotError, match="declared coverage"):
        service.import_snapshot(owners.dataset_key, assessor_bytes(1), next_day)
    assert state() == first
    service.import_snapshot(owners.dataset_key, assessor_bytes(), next_day)
    refreshed = state()
    assert len(refreshed) == 3 and refreshed[0]["address"] == "New field address"
    assert (
        refreshed[0]["projection_generation_id"] != first[0]["projection_generation_id"]
    )
    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)
    assert state() == refreshed
    owners.rights.shared_display = False
    service.register(owners)
    assert len(state()) == 3 and all(r["owner"] is None for r in state())


def test_field_reader_reconciled_pair_publishes_and_retry_is_idempotent(sources):
    parcels, owners = sources
    for source in sources:
        source.paired_datasets = [parcels.dataset_key, owners.dataset_key]
        service.register(source)
    missed = service.import_snapshot(owners.dataset_key, assessor_bytes(), DAY)
    assert missed["accepted"] == 0
    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)
    assert not records(
        "SELECT id FROM core.visible_parcel WHERE county_fips=:f", f=parcels.county_fips
    )
    assert service.retry_attempt(missed["attempt_id"])["status"] == "reconciled"

    def projection():
        return records(
            """SELECT v.id,v.projection_generation_id,owner.source_record_id
            FROM core.visible_parcel v JOIN evidence.reader_owner owner ON owner.subject_id=v.id
            WHERE v.county_fips=:f ORDER BY v.id""",
            f=parcels.county_fips,
        )

    visible = projection()
    assert len(visible) == 3
    service.retry_attempt(missed["attempt_id"])
    assert projection() == visible


def test_staged_same_date_correction_cannot_change_released_owner(sources):
    parcels, owners = sources
    for item in sources:
        item.paired_datasets = [parcels.dataset_key, owners.dataset_key]
        item.reader_release = "original"
        item.expected_snapshot_rows = 3
        service.register(item)
    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)
    service.import_snapshot(owners.dataset_key, assessor_bytes(), DAY)

    def owner_rows():
        return records(
            """SELECT projection_generation_id,value->>'value' AS name,verification_state
            FROM evidence.reader_owner WHERE dataset_key=:source ORDER BY subject_id""",
            source=owners.dataset_key,
        )

    original = owner_rows()
    assert len(original) == 3 and all(
        row["verification_state"] == "verified" for row in original
    )
    for item in sources:
        item.reader_release = "correction"
        service.register(item)
    workbook = load_workbook(BytesIO(assessor_bytes()))
    workbook.active["B2"] = "Corrected Owner LLC"
    output = BytesIO()
    workbook.save(output)
    service.import_snapshot(owners.dataset_key, output.getvalue(), DAY)
    assert owner_rows() == original
    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)
    revised = owner_rows()
    assert (
        revised[0]["projection_generation_id"]
        != original[0]["projection_generation_id"]
    )
    assert any(
        r["name"] == "Corrected Owner LLC" and r["verification_state"] == "verified"
        for r in revised
    )


def test_authorized_existing_snapshot_becomes_searchable_after_display_grant(sources):
    parcels, _ = sources
    parcels.rights.shared_display = False
    service.register(parcels)
    service.import_snapshot(parcels.dataset_key, parcel_bytes(), DAY)

    def visible():
        return records(
            "SELECT id FROM core.visible_parcel WHERE county_fips=:f",
            f=parcels.county_fips,
        )

    assert not visible()
    parcels.rights.shared_display = True
    service.register(parcels)
    assert len(visible()) == 3
