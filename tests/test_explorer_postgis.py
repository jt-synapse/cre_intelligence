"""Run with scripts/local-test-db on a disposable database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from cre.admin import provision
from cre.auth import identify
from cre.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("CRE_TEST_PLATFORM") != "1", reason="use scripts/local-test-db"
)


@pytest.fixture
def workspaces():
    owner = create_engine(os.environ["CRE_MIGRATION_URL"])
    ids = [uuid4(), uuid4()]
    names = [f"researcher-{uuid4()}", f"viewer-{uuid4()}"]
    with owner.begin() as c:
        for org, name, role in zip(ids, names, ("researcher", "viewer")):
            provision(c, org, "Explorer test", name, role, role == "researcher")

    def actor(authorization: str = Header()):
        return authorization.removeprefix("Bearer ")

    app.dependency_overrides[identify] = actor
    try:
        yield (
            owner,
            [
                (
                    TestClient(app),
                    {"Authorization": f"Bearer {n}", "X-Organization-ID": str(i)},
                )
                for i, n in zip(ids, names)
            ],
        )
    finally:
        app.dependency_overrides.pop(identify, None)
        owner.dispose()


def test_search_atomic_saves_and_grouping(workspaces):
    _, ((api, auth), (other, viewer)) = workspaces

    def get(q):
        return (
            api.get("/v1/parcels", params={"county_fips": "99001", **q}, headers=auth)
            .raise_for_status()
            .json()["features"]
        )

    match = get({"q": "0001-A-001"})
    assert len(match) == 1
    first = match[0]["id"]
    assert get({"point": "-84.0095,33.9505"})[0]["id"] == first
    assert first in [f["id"] for f in get({"bbox": "-84.011,33.949,-84.007,33.952"})]
    assert api.get("/v1/parcels?bbox=nan,0,1,1", headers=auth).status_code == 422
    record = api.get(f"/v1/parcels/{first}", headers=auth).json()
    assert record["geometry"]["type"] == "MultiPolygon"
    assert any(
        c["predicate"] == "assessor_listed_owner" and c["locator"]
        for c in record["claims"]
    )

    def save(pid):
        return (
            api.post("/v1/workspace/saves", json={"parcel_id": pid}, headers=auth)
            .raise_for_status()
            .json()["property_id"]
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        pids = list(pool.map(save, [first] * 4))
    assert len(set(pids)) == 1
    property_id = pids[0]
    assert not other.get("/v1/workspace/saves", headers=viewer).json()["items"]
    assert (
        other.post(
            "/v1/workspace/saves", json={"parcel_id": first}, headers=viewer
        ).status_code
        == 403
    )
    assert (
        api.get(
            "/v1/workspace/saves",
            headers={**auth, "X-Organization-ID": viewer["X-Organization-ID"]},
        ).status_code
        == 403
    )
    second = get({"q": "0002 A 001"})[0]["id"]
    secondary = save(second)
    pf = (
        api.post("/v1/portfolios", json={"name": "Acquisitions"}, headers=auth)
        .raise_for_status()
        .json()["id"]
    )
    api.put(
        f"/v1/portfolios/{pf}/properties/{secondary}", headers=auth
    ).raise_for_status()
    grouped = api.post(
        f"/v1/properties/{property_id}/grouping",
        json={
            "merge_property_ids": [secondary],
            "name": "Example Commerce",
            "reason": "Reviewed synthetic grouping",
        },
        headers=auth,
    )
    assert grouped.raise_for_status().json()["property_status"] == "confirmed"
    assert len(grouped.json()["parcels"]) >= 2
    assert (
        api.get(f"/v1/properties/{secondary}", headers=auth).json()["id"] == property_id
    )
    assert [
        x["property_id"]
        for x in api.get("/v1/workspace/saves", headers=auth).json()["items"]
    ] == [property_id]
    assert api.get("/v1/portfolios", headers=auth).json()["items"][0][
        "property_ids"
    ] == [property_id]


def test_screening_unknown_intersection_and_reviewed_extent(workspaces):
    import json

    from cre.screening import Layer, publish

    owner, ((api, auth), _) = workspaces
    ring = [
        [-84.01, 33.95],
        [-84.009, 33.95],
        [-84.009, 33.951],
        [-84.01, 33.951],
        [-84.01, 33.95],
    ]
    geo = {"type": "Polygon", "coordinates": [ring]}
    data = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": geo, "properties": {"zone": "fixture"}}
            ],
        }
    ).encode()
    meta = dict(
        dataset_key="test-" + str(uuid4()),
        kind="zoning",
        reference="Fictional geometry",
        observed_on=date(2026, 1, 1),
        rights_reference="Project-owned fixture",
        permitted_manual_import=True,
        permitted_retention=True,
        shared_display=True,
        label_field="zone",
        coverage={
            "type": "Polygon",
            "coordinates": [
                [
                    [-84.02, 33.94],
                    [-84, 33.94],
                    [-84, 33.96],
                    [-84.02, 33.96],
                    [-84.02, 33.94],
                ]
            ],
        },
    )
    with owner.begin() as c:
        publish(c, Layer(**meta), data)

    def results(pin):
        pid = api.get(
            "/v1/parcels", params={"q": pin, "county_fips": "99001"}, headers=auth
        ).json()["features"][0]["id"]
        return [
            r["result"]
            for r in api.get("/v1/parcels/" + pid, headers=auth).json()["screening"]
            if r["dataset_key"] == meta["dataset_key"]
        ]

    assert results("0001 A 001") == ["intersection"]
    assert results("0002 A 001") == ["screened_no_match"]
    with owner.begin() as c:
        c.execute(
            text(
                "UPDATE core.screening_layer SET shared_display=false WHERE dataset_key=:k"
            ),
            {"k": meta["dataset_key"]},
        )
    assert results("0001 A 001") == []


def test_rls_is_enforced_without_api_predicate(workspaces):
    from cre.db import engine, tenant_scope

    _, ((api, auth), (_, other)) = workspaces
    pf = api.post(
        "/v1/portfolios", json={"name": "Private portfolio"}, headers=auth
    ).json()["id"]
    with engine().begin() as c:
        tenant_scope(c, UUID(other["X-Organization-ID"]))
        assert (
            c.scalar(
                text("select count(*) from operations.portfolio where id=:id"),
                {"id": pf},
            )
            == 0
        )


def test_phone_parcel_summary_owner_search_versions_and_tiles(workspaces):
    _, ((api, auth), _) = workspaces
    features = (
        api.get(
            "/v1/parcels", params={"q": "Example Commerce Holdings LLC"}, headers=auth
        )
        .raise_for_status()
        .json()["features"]
    )
    assert len(features) == 2
    props = features[0]["properties"]
    version = props["projection_generation_id"]
    UUID(props["geometry_version_id"])
    assert props["reader_version"] == version
    item = (
        api.get(
            "/v1/parcels/" + features[0]["id"],
            params={"generation": version},
            headers=auth,
        )
        .raise_for_status()
        .json()
    )
    summary = (
        api.get(
            "/v1/parcels/" + features[0]["id"],
            params={"summary": True, "generation": version},
            headers=auth,
        )
        .raise_for_status()
        .json()
    )
    assert "geometry" not in summary and "claims" not in summary
    assert (
        summary["owners"] == item["owners"]
        and summary["map_destination"]["type"] == "Point"
    )
    for mode in ("party", "mailing", "control"):
        related = api.get(
            "/v1/parcels/" + features[0]["id"] + "/related",
            params={"generation": version, "mode": mode},
            headers=auth,
        )
        assert related.raise_for_status().json()["features"] == []
    assert item["projection_generation_id"] == version
    assert item["owners"][0]["name"] == "Example Commerce Holdings LLC"
    stale = api.get(
        "/v1/parcels/" + features[0]["id"],
        params={"generation": str(uuid4())},
        headers=auth,
    )
    assert stale.status_code == 409
    tile = api.get(f"/v1/tiles/{version}/0/0/0", headers=auth)
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert api.get(f"/v1/tiles/{version}/1/9/0", headers=auth).status_code == 422
