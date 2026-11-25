import os
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_folder_and_pin_names_are_trimmed_and_require_readable_labels():
    from cre.field_places import Folder, Pin

    assert Folder(name="  North tour  ", color="teal").name == "North tour"
    assert Pin(label="  East access  ").label == "East access"
    with pytest.raises(ValidationError):
        Folder(name="  ", color="orange")
    with pytest.raises(ValidationError):
        Folder(name="West", color="not a color")
    with pytest.raises(ValidationError):
        Pin(label="  ")


@pytest.mark.skipif(
    os.getenv("CRE_TEST_PLATFORM") != "1", reason="use scripts/local-test-db"
)
def test_shared_pins_visits_and_folder_privacy(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    from cre.admin import provision
    from cre.auth import identify
    from cre.main import app

    org, other = uuid4(), uuid4()
    actor = "field-" + uuid4().hex
    viewer = "viewer-" + uuid4().hex
    owner = create_engine(os.environ["CRE_MIGRATION_URL"])
    with owner.begin() as conn:
        provision(conn, org, "Field workspace", actor, "analyst")
        provision(conn, org, "Field workspace", viewer, "viewer")
        provision(conn, other, "Second workspace", actor, "admin")
    who = actor
    monkeypatch.setitem(app.dependency_overrides, identify, lambda: who)
    api = TestClient(app)
    auth, foreign = [{"X-Organization-ID": str(x)} for x in (org, other)]
    base = "/v1/field/places"
    features = (
        api.get("/v1/parcels?county_fips=99001", headers=auth)
        .raise_for_status()
        .json()["features"]
    )
    pid, other_pid = (f["id"] for f in features[:2])
    parcel = base + "/parcels/" + pid
    body = {"name": "North tour", "color": "amber"}
    folder = (
        api.post(base + "/folders", json=body, headers=auth).raise_for_status().json()
    )
    assert (
        api.post(base + "/folders", json=body, headers=auth).raise_for_status().json()
        == folder
    )
    assert (
        api.post(
            base + "/folders", json={**body, "color": "teal"}, headers=auth
        ).status_code
        == 409
    )
    pin = {"label": "Walk frontage", "folder_id": folder["id"]}
    assert api.put(parcel + "/pin", json=pin, headers=foreign).status_code == 404
    for _ in range(2):
        api.put(parcel + "/pin", json=pin, headers=auth).raise_for_status()
    op = {"operation_id": str(uuid4())}
    visit = (
        api.post(parcel + "/visits", json=op, headers=auth).raise_for_status().json()
    )
    assert api.post(parcel + "/visits", json=op, headers=auth).json() == visit
    assert (
        api.post(
            base + "/parcels/" + other_pid + "/visits", json=op, headers=auth
        ).status_code
        == 409
    )
    assert api.get(base, headers=foreign).json() == {"folders": [], "pins": []}
    assert api.get(parcel + "/visits", headers=foreign).json()["items"] == []
    who = viewer
    assert api.get(parcel + "/visits", headers=auth).json()["items"] == [visit]
    result = api.get(base, headers=auth).raise_for_status().json()
    assert result["folders"] == [folder]
    assert len(result["pins"]) == 1
    assert result["pins"][0]["last_visited_at"] == visit["visited_at"]
    assert result["pins"][0]["label"] == pin["label"]
    assert api.put(parcel + "/pin", json=pin, headers=auth).status_code == 403
    assert api.post(parcel + "/visits", json=op, headers=auth).status_code == 403
    who = actor
    api.put(
        parcel + "/pin", json={"label": "Recheck", "folder_id": None}, headers=auth
    ).raise_for_status()
    assert api.get(base, headers=auth).json()["pins"][0]["folder_id"] is None
    # Withdraw and restore this shared test fixture around the rights checks.
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE provenance.source_dataset SET shared_display=false WHERE dataset_key='demo_parcels'"
            )
        )
    try:
        assert api.get(base, headers=auth).json()["pins"] == []
        assert api.get(parcel + "/visits", headers=auth).status_code == 404
        assert api.put(parcel + "/pin", json=pin, headers=auth).status_code == 404
    finally:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "UPDATE provenance.source_dataset SET shared_display=true WHERE dataset_key='demo_parcels'"
                )
            )
        owner.dispose()
