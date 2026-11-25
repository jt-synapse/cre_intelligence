from cre.ingestion import gwinnett_address_points as points


def test_lookup_keeps_the_entire_queried_unit_and_building():
    row = {
        "FULLADDR": "41 Main Rd, BLDG 3 UNIT 007-A",
        "ADDRNUM": "41",
        "FULLNAME": "Main Rd",
        "UNITTYPE": "BLDG",
        "UNITID": "3",
        "ALTUNITTYPE": "UNIT",
        "ALTUNITID": "007-A",
    }
    matches = points.address_keys(row)
    assert matches["41 MAIN RD BLDG 3 UNIT 007-A"] == "full_address"
    assert matches["41 MAIN RD 007-A"] == "unit_id"
    assert matches["41 MAIN RD UNIT 007-A"] == "unit_id"
    assert matches["41 MAIN RD 3 - 007-A"] == "unit_pair"
    assert "41 MAIN RD" not in matches
    assert "41 MAIN RD 007" not in matches
    assert "41 MAIN RD 7-A" not in matches
    assert "41 MAIN RD 4 - 007-A" not in matches
    assert "41 MAIN RD 3 - 3" not in matches
    # A qualifier with no literal counterpart in the full address cannot create an alias.
    assert list(points.address_keys(dict(row, FULLADDR="41-45 MAIN RD"))) == [
        "41-45 MAIN RD"
    ]


def test_failed_or_competing_point_evidence_cannot_create_a_unique_result():
    base = {"parcel_id": "one", "normalized_pin": "P1", "address_sources": []}
    other = {"parcel_id": "two", "normalized_pin": "P2", "address_sources": []}
    ev = {"dataset": "points", "locator": {"object_id": 3}}
    assert points.combine([base], [(None, "P2", ev)])[0] == []
    both, _ = points.combine([base], [(other, "P2", ev)])
    assert [p["normalized_pin"] for p in both] == ["P1", "P2"]
    same, _ = points.combine([base], [(base, "P1", ev), (None, "P1", ev)])
    assert len(same) == 1 and same[0]["address_sources"] == [ev]


def test_point_key_and_polygon_disagreement_holds_a_single_situs_match():
    base = {"parcel_id": "one", "normalized_pin": "P1", "address_sources": []}
    evidence = {"covering_pins": ["P2"]}
    found, rejected = points.combine([base], [(None, "P1", evidence)])
    assert found == []
    assert rejected == [{"point_pin": "P1", "covering_pins": ["P2"]}]


def test_verified_geometry_can_reconcile_only_the_same_county_point():
    unit = {
        "parcel_id": "private:unit:1",
        "normalized_pin": "U1",
        "address_sources": [],
        "verified_point_oids": [18],
        "geometry_role": "shared_common_polygon",
        "geometry_pin": "COMMON",
    }
    point = {
        "dataset": points.DATASET,
        "artifact_sha256": points.DIGEST,
        "locator": {"object_id": 18},
        "covering_pins": ["COMMON"],
    }
    found, rejected = points.combine([unit], [(None, "U1", point)])
    assert [p["parcel_id"] for p in found] == [unit["parcel_id"]]
    assert not rejected
    for bad in (
        dict(point, locator={"object_id": 19}),
        dict(point, covering_pins=["OTHER"]),
        dict(point, covering_pins=["COMMON", "OTHER"]),
        dict(point, artifact_sha256="older"),
    ):
        assert points.combine([unit], [(None, "U1", bad)])[0] == []
    assert not points.combine([unit], [(None, "OTHER", point)])[0]
    direct = dict(
        unit, normalized_pin="P1", geometry_pin="P1", geometry_role="direct_polygon"
    )
    found, rejected = points.combine(
        [direct], [(None, "P1", dict(point, covering_pins=[]))]
    )
    assert found and not rejected
