import os
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_same_geometry_is_deduplicated_but_competing_versions_cannot_replace_it():
    from cre.field_sites import Selection

    member = {"parcel_id": uuid4(), "geometry_version_id": uuid4()}
    selection = Selection(reader_version=str(uuid4()), members=[member] * 21)
    assert len(selection.members) == 1
    for invalid in (
        [],
        [member, {**member, "geometry_version_id": uuid4()}],
        [{"parcel_id": uuid4(), "geometry_version_id": uuid4()} for _ in range(21)],
    ):
        with pytest.raises(ValidationError):
            Selection(reader_version=str(uuid4()), members=invalid)


def test_grouped_assessments_preserve_unknown_ownership_and_missing_values():
    from cre.field_sites import summarize_claims

    ids = [uuid4() for _ in range(4)]
    records = [
        {
            "parcel_id": ids[0],
            "predicate": "assessed_value",
            "value": {"value": 100, "tax_year": 2025, "currency": "USD"},
        },
        {
            "parcel_id": ids[1],
            "predicate": "assessed_value",
            "value": {"value": 200, "tax_year": 2026, "currency": "USD"},
        },
        {
            "parcel_id": ids[2],
            "predicate": "assessed_value",
            "value": {"value": 400, "tax_year": 2026, "currency": "EUR"},
        },
        {"parcel_id": ids[0], "predicate": "deeded_acres", "value": {"value": 2.5}},
        {
            "parcel_id": ids[0],
            "predicate": "recorded_owner",
            "value": {"party_id": "a"},
        },
        {
            "parcel_id": ids[1],
            "predicate": "recorded_owner",
            "value": {"party_id": "a"},
        },
        {
            "parcel_id": ids[2],
            "predicate": "assessor_listed_owner",
            "value": {"party_id": "a"},
        },
    ]
    facts = summarize_claims(
        ids, [dict(r, verification_state="verified") for r in records]
    )
    assert facts["assessment_groups"] == [
        {"year": 2025, "currency": "USD", "subtotal": 100, "covered_members": 1},
        {"year": 2026, "currency": "EUR", "subtotal": 400, "covered_members": 1},
        {"year": 2026, "currency": "USD", "subtotal": 200, "covered_members": 1},
    ]
    assert facts["combined_assessment"] is None
    assert facts["ownership"] == {"known_recorded_parties": 1, "unresolved_members": 2}
    assert facts["source_acres"] == {"subtotal": Decimal("2.5"), "covered_members": 1}


@pytest.mark.skipif(
    os.getenv("CRE_TEST_PLATFORM") != "1",
    reason="use scripts/local-test-db",
)
def test_six_parcel_union_revisions_generation_and_revocation(monkeypatch, tmp_path):
    import json
    import os
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    from pathlib import Path
    from time import monotonic

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    from cre.admin import provision
    from cre.auth import identify
    from cre.ingestion.contract import Manifest
    from cre.ingestion.demo import assessor_bytes, parcel_bytes
    from cre.ingestion.service import import_snapshot, register
    from cre.main import app

    suffix = uuid4().hex[:10]
    county = "98501"
    owner_url = os.environ["CRE_MIGRATION_URL"]
    owner = create_engine(owner_url)
    names = {kind: "field_site_" + kind + suffix for kind in ("parcels", "assessor")}
    data = json.loads(parcel_bytes(6))
    for feature, (x, y) in zip(
        data["features"], [(0, 0), (5, 0), (15, 0), (25, 10), (45, 0), (45, 0)]
    ):
        feature["geometry"]["coordinates"] = [
            [
                [a / 10000, b / 10000]
                for a, b in [(x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10), (x, y)]
            ]
        ]
    payload = json.dumps(data).encode()
    monkeypatch.setenv("CRE_STORAGE_DIR", str(tmp_path))
    with monkeypatch.context() as env:
        env.setenv("DATABASE_URL", owner_url)
        for kind, raw in (("parcels", payload), ("assessor", assessor_bytes(6))):
            manifest = json.loads(Path(f"contracts/demo_{kind}.json").read_text())
            manifest.update(
                dataset_key=names[kind],
                county_fips=county,
                paired_datasets=[],
                expected_snapshot_rows=6,
            )
            register(Manifest.model_validate(manifest))
            assert import_snapshot(names[kind], raw, date(2026, 1, 10))["accepted"] == 6

    org, other, other_editor = uuid4(), uuid4(), uuid4()
    who = "field-site-" + suffix
    with owner.begin() as conn:
        provision(conn, org, "Field site editor", who, "researcher")
        provision(conn, other, "Other workspace", who, "viewer")
        provision(conn, other_editor, "Other editor workspace", who, "admin")
    monkeypatch.setitem(app.dependency_overrides, identify, lambda: who)
    api = TestClient(app)
    headers = {"X-Organization-ID": str(org)}
    foreign = {"X-Organization-ID": str(other)}
    path = "/v1/field/sites"
    features = (
        api.get("/v1/parcels", params={"county_fips": county}, headers=headers)
        .raise_for_status()
        .json()["features"]
    )
    refs = [
        {
            "parcel_id": f["id"],
            "geometry_version_id": f["properties"]["geometry_version_id"],
        }
        for f in features
    ]
    assert len(refs) == 6
    body = {
        "reader_version": features[0]["properties"]["reader_version"],
        "members": refs,
    }
    start = monotonic()
    result = (
        api.post(path + "/preview", json=body, headers=headers)
        .raise_for_status()
        .json()
    )
    assert monotonic() - start < 2.0
    assert result["area_m2"] == pytest.approx(12309.07 * 4.5, rel=0.0001)
    assert result["member_count"] == 6
    assert result["disconnected"] and len(result["components"]) == 3
    assert result["point_only_contacts"] == [
        [refs[2]["parcel_id"], refs[3]["parcel_id"]]
    ]
    assert result["claim_sources"] and all(
        m["source_record_id"] for m in result["members"]
    )
    assert not api.get(path, headers=headers).json()["items"]
    assert (
        api.post(path, json={**body, "name": "Denied"}, headers=foreign).status_code
        == 403
    )
    first = (
        api.post(path, json={**body, "name": "Site one"}, headers=headers)
        .raise_for_status()
        .json()
    )
    site = path + "/" + first["id"]
    assert [s["id"] for s in api.get(path, headers=headers).json()["items"]] == [
        first["id"]
    ]
    edit_payload = {**body, "name": "Different workspace", "expected_revision": 1}
    assert api.put(site, json=edit_payload, headers=foreign).status_code == 403
    assert (
        api.put(
            site, json=edit_payload, headers={"X-Organization-ID": str(other_editor)}
        ).status_code
        == 404
    )
    from cre.db import engine, tenant_scope

    with engine().begin() as conn:
        tenant_scope(conn, other_editor)
        for table, column in (
            ("field_site", "id"),
            ("field_site_revision", "site_id"),
            ("field_site_member", "site_id"),
            ("field_site_claim", "site_id"),
        ):
            assert (
                conn.scalar(
                    text(f"SELECT count(*) FROM operations.{table} WHERE {column}=:id"),
                    {"id": first["id"]},
                )
                == 0
            )
    assert api.get(site, headers=foreign).status_code == 404
    assert api.get(path, headers=foreign).json()["items"] == []

    def edit(n):
        return api.put(
            site,
            json={
                **body,
                "members": refs[:3],
                "name": f"Revision {n}",
                "expected_revision": 1,
            },
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(edit, [1, 2]))
    assert sorted(r.status_code for r in attempts) == [200, 409]
    assert api.get(site, headers=headers).json()["member_count"] == 3
    assert (
        api.get(site + "?revision=1", headers=headers).json()["area_m2"]
        == first["area_m2"]
    )
    with monkeypatch.context() as env:
        env.setenv("DATABASE_URL", owner_url)
        assert (
            import_snapshot(names["parcels"], payload, date(2026, 2, 10))["accepted"]
            == 6
        )
    assert api.post(path + "/preview", json=body, headers=headers).status_code == 409
    assert (
        api.post(path, json={**body, "name": "Stale save"}, headers=headers).status_code
        == 409
    )
    assert (
        api.put(
            site,
            json={**body, "name": "Stale revision", "expected_revision": 2},
            headers=headers,
        ).status_code
        == 409
    )
    saved = api.get(path, headers=headers).raise_for_status().json()["items"]
    assert [(s["id"], s["revision"]) for s in saved] == [(first["id"], 2)]
    historical = (
        api.get(site + "?revision=1", headers=headers).raise_for_status().json()
    )
    assert (
        historical["members"] == first["members"]
        and historical["reader_version"] == body["reader_version"]
    )
    assert historical["assessment_groups"]
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE provenance.source_dataset SET shared_display=false WHERE dataset_key=:k"
            ),
            {"k": names["assessor"]},
        )
    redacted = api.get(site + "?revision=1", headers=headers).raise_for_status().json()
    assert redacted["assessment_groups"] == [] and all(
        c["dataset_key"] != names["assessor"] for c in redacted["claim_sources"]
    )
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE provenance.source_dataset SET shared_display=false WHERE dataset_key=:k"
            ),
            {"k": names["parcels"]},
        )
    assert api.get(site, headers=headers).status_code == 404
    assert api.get(path, headers=headers).json()["items"] == []
    owner.dispose()
