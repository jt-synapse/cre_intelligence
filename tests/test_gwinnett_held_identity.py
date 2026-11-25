import os

import pytest
from sqlalchemy import create_engine

from cre.ingestion import gwinnett_held_identity as held


def point(oid, pin, street, **other):
    return {
        "properties": {
            "OBJECTID": oid,
            "PIN": pin,
            "FULLADDR": street,
            "SITEADDID": f"site-{oid}",
            "STATUS": "Primary",
            "POINTTYPE": "Building",
            "ADDRNUM": "40",
            "FULLNAME": "ELM ST",
            **other,
        },
        "geometry": {"coordinates": [2, 2]},
    }


def polygon(pin="P1", tax="T1", gid="G1", lrs=9, ring=None):
    return {
        "properties": {
            "PIN": pin,
            "TAXPIN": tax,
            "GlobalID": gid,
            "LRSN": lrs,
            "ADDRESS": "40",
            "OBJECTID": 33,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [ring or [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
        },
    }


def test_unqualified_address_considers_all_buildings_and_requires_exact_primary():
    rows = [
        point(1, "P1", "40 ELM ST"),
        point(2, "P2", "40 ELM ST, BLDG B", STATUS="Secondary"),
        point(3, "P3", "40 ELM ST, BLDG C", STATUS="Retired"),
        point(4, "P4", "40 ELM ST, BLDG D", POINTTYPE="Condo"),
    ]
    primary, competing = held.address_points(rows, {"40 ELM ST", "40 ELM ST BLDG D"})
    assert [p["oid"] for p in primary["40 ELM ST"]] == [1]
    assert competing["40 ELM ST"] == {"P1", "P2", "P4"}
    assert not primary.get("40 ELM ST BLDG D")


def test_only_lrsn_may_collide_in_the_full_original_and_coverage_is_not_pin_filtered():
    hit = {"oid": 45, "x": 2, "y": 2, "pin": "P1"}
    rows = [polygon(), polygon("P2", "T2", "G2"), polygon("P3", "T3", "G3", 33)]
    eligible, envelopes = held.parcel_evidence(
        rows, [hit], {0: {"external_record_id": "G1"}}
    )
    assert set(eligible) == {"P1"}
    assert eligible["P1"]["lrsn_features"] == 2
    assert {entry["feature"] for entry in envelopes} == {0, 1, 2}
    for column, shared in (("GlobalID", "G1"), ("TAXPIN", "T1"), ("PIN", "P-1")):
        changed = polygon("P2", "T2", "G2")
        changed["properties"][column] = shared
        assert not held.parcel_evidence(
            [rows[0], changed], [hit], {0: {"external_record_id": "G1"}}
        )[0]


@pytest.mark.integration
def test_native_geometry_requires_unique_cover_and_strict_interior():
    url = os.getenv("CRE_INGEST_TEST_URL")
    if not url:
        pytest.skip("requires a disposable PostGIS database")

    def cover(oid, x, y, feature, geom):
        return {"oid": oid, "x": x, "y": y, "feature": feature, "geom": geom}

    square = polygon()["geometry"]
    tri = polygon(ring=[[0, 0], [4, 0], [0, 4], [0, 0]])["geometry"]
    checks = [
        cover(1, 3, 3, 0, square),
        cover(1, 3, 3, 1, tri),
        cover(2, 2, 2, 0, square),
        cover(2, 2, 2, 1, tri),
        cover(3, 4, 4, 0, square),
        cover(4, 2, 2, 0, square),
        cover(4, 2, 2, 1, None),
    ]
    with create_engine(url).connect() as conn:
        assert held.unique_interiors(conn, checks) == {1: 0}


def test_held_identity_requires_two_exact_streets_and_preserves_both_source_keys():
    run = {"run_id": "publication", "artifact_sha256": "snapshot"}
    geo_rec = {
        "locator": {"feature": 10},
        "source_record_id": "geo-record",
        "review_id": "geo-review",
    }
    tax_rec = {
        "locator": {"workbook": held.OWNER, "sheet": held.SHEET, "row": 12},
        "source_record_id": "tax-record",
        "review_id": "tax-review",
    }
    parcel = {
        "feature": 10,
        "properties": polygon()["properties"],
        "hold": geo_rec,
        "lrsn_features": 3,
    }
    hit = {"pin": "P1", "oid": 7, "site": "s", "number": "40"}

    def resolve(street, competing, interiors):
        return held.review_candidate(
            "40 ELM ST",
            [hit],
            competing,
            parcel,
            interiors,
            (12, "T1", "18", street),
            tax_rec,
            run,
            run,
        )

    match, review = resolve("40 Elm St", {"P1"}, {7: 10})
    assert review is None and match["normalized_pin"] == "P1"
    assert match["parcel_id"] != geo_rec["source_record_id"]
    assert match["identity_scope"] == "private_evaluation"
    assert match["geometry_source"]["locator"] == {"feature": 10, "field": "geometry"}
    assert match["verified_point_oids"] == [7]
    assert match["secondary_identifier_review"]["gis_lrsn"] == 9
    assert match["secondary_identifier_review"]["assessor_lrsn"] == "18"
    assert resolve("40 Elm St BLDG C", {"P1"}, {7: 10}) == (None, None)
    assert resolve("40 Elm St", {"P1", "P2"}, {7: 10})[0] is None
    assert resolve("40 Elm St", {"P1"}, {7: 2})[1]["point_pin"] == "P1"


@pytest.mark.parametrize("acreage", [-1, float("inf"), float("nan")])
def test_collision_does_not_hide_invalid_acreage(acreage):
    source = polygon()
    source["properties"]["CALCULATEDACREAGE"] = acreage
    peer = polygon("P2", "T2", "G2")
    eligible, _ = held.parcel_evidence(
        [source, peer],
        [{"pin": "P1", "oid": 1, "x": 2, "y": 2}],
        {0: {"external_record_id": "G1"}},
    )
    assert not eligible


def test_unlocatable_source_polygon_prevents_a_unique_cover():
    source = polygon()
    source["geometry"] = None
    with pytest.raises(held.SnapshotError, match="envelope"):
        held.parcel_evidence([source], [{"pin": "P1", "oid": 1, "x": 2, "y": 2}], {})
