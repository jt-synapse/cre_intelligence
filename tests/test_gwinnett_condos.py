import pytest

from cre.ingestion import gwinnett_condos as condos


def evidence():
    row = {
        "OBJECTID": 17,
        "PIN": "5070 A",
        "RPIN": "R-0107",
        "COMMON_PIN": "5070 X",
        "LRSN": 451,
        "LOCADDR": "95 Market Dr",
    }
    row2 = dict(row, OBJECTID=18, PIN="5070 B", RPIN="T-670", LRSN=942)
    assessor = {
        "R-0107": (12, "R-0107", "451", "95 MARKET DR"),
        "T-670": (13, "T-670", "942", "95 Market Dr"),
    }
    pts = {
        pin: [
            {
                "oid": i,
                "site": "site" + str(i),
                "common": "5070X",
                "status": "Primary",
                "kind": "Condo",
                "x": 500,
                "y": 600,
            }
        ]
        for pin, i in (("5070A", 32), ("5070B", 35))
    }
    parent = {
        "parcel_id": "core-common",
        "normalized_pin": "5070X",
        "source_record_id": "parent-record",
        "locator": {"feature": 42},
        "interior": True,
    }
    covers = {32: [dict(parent)], 35: [dict(parent)]}
    sources = {
        "gwinnett_parcels": {"run_id": "gis"},
        "gwinnett_assessor": {"run_id": "roll"},
    }
    return [row, row2], assessor, pts, covers, sources


def resolve(rows, assessor, pts, covers, sources, direct=frozenset()):
    return condos.resolve_units(
        rows,
        ["95 MARKET DR", "95 MARKET CT"],
        assessor=assessor,
        points=pts,
        covering=covers,
        raw_direct=direct,
        sources=sources,
    )


def test_same_street_and_parent_preserve_each_verified_condo_identity():
    rows, assessor, pts, covers, sources = evidence()
    (hits, other), (rejected, ignored) = resolve(rows, assessor, pts, covers, sources)
    assert sorted(h["normalized_pin"] for h in hits) == ["5070A", "5070B"]
    assert len({h["parcel_id"] for h in hits}) == 2
    assert all(
        h["parcel_id"] != "core-common" and h["geometry_parcel_id"] == "core-common"
        for h in hits
    )
    assert all(
        h["geometry_role"] == "shared_common_polygon" and h["geometry_pin"] == "5070X"
        for h in hits
    )
    assert hits[0]["verified_point_oids"] == [32]
    assert hits[0]["pin_source"]["locator"]["object_id"] == 17
    assert hits[0]["geometry_source"]["source_record_id"] == "parent-record"
    table, roll = hits[0]["tax_key_sources"]
    assert table["locator"]["fields"] == ["RPIN", "LRSN"]
    assert roll["locator"]["fields"] == ["PIN", "LRSNum"]
    assert roll["locator"]["row"] == 12
    assert len(roll["workbook_sha256"]) == 64
    assert {"LOCADDR", "PROPERTYSTREET"} == {
        s["locator"]["field"] for s in hits[0]["address_sources"]
    }
    assert not other and not rejected and not ignored


@pytest.mark.parametrize(
    "conflict",
    [
        "key",
        "parent",
        "boundary",
        "overlap",
        "roll",
        "raw_child",
        "missing_primary",
        "row_key_collision",
    ],
)
def test_unresolved_sibling_is_retained_and_cannot_be_declared_unique(conflict):
    rows, assessor, pts, covers, sources = evidence()
    direct = set()
    if conflict == "key":
        rows[1]["RPIN"] = "R-0107"
    elif conflict == "parent":
        pts["5070B"].append(
            dict(pts["5070B"][0], oid=36, common="OTHER", status="Secondary")
        )
    elif conflict == "boundary":
        covers[35][0]["interior"] = False
    elif conflict == "overlap":
        covers[35].append(dict(covers[35][0], normalized_pin="OTHER"))
    elif conflict == "roll":
        assessor["T-670"] = (13, "T-670", "941", "95 Market Dr")
    elif conflict == "raw_child":
        direct.add("5070B")
    elif conflict == "missing_primary":
        pts["5070B"][0]["status"] = "Secondary"
    else:
        rows.append(dict(rows[1], OBJECTID=19, LOCADDR="Unrelated street"))
    (hits, _), (bad, _) = resolve(rows, assessor, pts, covers, sources, direct)
    assert not any(h["normalized_pin"] == "5070B" for h in hits)
    assert any(h["point_pin"] == "5070B" for h in bad)
