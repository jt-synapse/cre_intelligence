from datetime import date

from cre.ingestion import gwinnett_lookup as lookup


def test_document_queries_preserve_building_suite_and_final_letter():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    def row(i, address):
        return {"record_id": i, "address": address}

    records = [
        row("a", "71 MAIN RD BLDG 400 SUITE 10-A"),
        row("b", "71 MAIN RD STE 10"),
        row("c", "71 MAIN RD"),
    ]
    hits = docs.address_hits(
        ["71 main rd 400 - 10-A", "71 MAIN RD 10-A", "71 MAIN RD 10", "71 MAIN RD"],
        records,
    )
    assert [[r["record_id"] for r in rows] for rows in hits] == [
        ["a"],
        [],
        ["b"],
        ["c"],
    ]


def test_dated_authorization_site_witness_and_competing_pins():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    parcel = {"normalized_pin": "6123001", "parcel_id": "p", "address_sources": []}
    witness = {**parcel, "address_sources": [{"site": "71 MAIN RD"}]}
    row = {
        "record_id": "plan-1",
        "parcel_id": "6123 001",
        "eligible": True,
        "status_date": "2026-11-07",
        "dataset": docs.DATASET,
        "record_status": "Plans Authorized",
        "source_sha256": "a" * 64,
        "source_url": "https://example.org/plan",
        "locator": {"page": 2},
        "address": "71 MAIN RD STE 1",
        "record_type": "Commercial Plan",
    }
    assert (
        docs.resolve([], [row], witness, held=False)[0]["address_sources"][-1][
            "record_id"
        ]
        == "plan-1"
    )
    assert docs.resolve([], [row], None, held=False) == []
    assert docs.resolve([], [row], witness, held=True) == []
    assert docs.resolve([], [{**row, "eligible": False}], witness, held=False) == []
    assert (
        docs.resolve(
            [],
            [{**row, "status_date": date(2026, 11, 9).isoformat()}],
            witness,
            held=False,
        )
        == []
    )
    conflict = {
        **row,
        "record_id": "intake-2",
        "eligible": False,
        "parcel_id": "6123 999",
    }
    assert docs.resolve([parcel], [row, conflict], witness, held=False) == []
    rival = {**parcel, "parcel_id": "q", "normalized_pin": "6123999"}
    assert docs.resolve([parcel, rival], [row], witness, held=False) == [parcel, rival]


def test_primary_point_witness_vetoes_a_multi_parcel_street():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    def point(i, street, pin, status):
        return {
            "properties": {
                "ADDRNUM": "71",
                "FULLNAME": street,
                "STATUS": status,
                "PIN": pin,
                "OBJECTID": i,
            },
            "geometry": {"coordinates": [i, 1]},
        }

    features = [
        point(1, "MAIN RD", "6123 001", "Primary"),
        point(2, "MAIN RD", "6123 002", "Secondary"),
        point(3, "OAK RD", "6123 001", "Primary"),
        point(4, "PINE RD", "6123 001", "Tertiary"),
    ]
    witnesses = docs.primary_sites(
        ["71 MAIN RD 7", "71 OAK RD 7", "71 PINE RD 7", "71 MAPLE RD 7"], features
    )
    assert [w["primary"][0]["oid"] if w else None for w in witnesses] == [
        None,
        3,
        None,
        None,
    ]


def test_plan_occupancy_mode_includes_point_and_identity_guards(monkeypatch, capsys):
    import json

    def retrieve(addresses, *, point_audit, identity_audit, document_audit):
        for audit in (point_audit, identity_audit, document_audit):
            audit.extend([[{"id": "source"}] for _ in addresses])
        return {}, [[] for _ in addresses]

    monkeypatch.setattr(lookup, "fetch_candidates", retrieve)
    assert lookup.main(["lookup-address", "71 MAIN RD STE 1", "--plan-occupancy"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["plan_occupancy_records"] == [{"id": "source"}]
    assert result["unresolved_parcel_identities"] == result["unresolved_address_points"]


def test_site_witness_does_not_treat_a_street_extension_as_a_suite():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    feature = {
        "properties": {
            "ADDRNUM": "71",
            "FULLNAME": "MAIN RD",
            "STATUS": "Primary",
            "PIN": "6123 001",
            "OBJECTID": 7,
        },
        "geometry": {"coordinates": [1, 1]},
    }
    assert docs.primary_sites(["71 MAIN RD EXT 7"], [feature]) == [None]


def test_use_second_primary_when_only_it_has_parcel_coverage():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    site = {
        "street": "71 MAIN RD",
        "pin": "6123001",
        "primary": [{"oid": 1, "x": 1, "y": 1}, {"oid": 2, "x": 5, "y": 5}],
    }
    coverage = {
        2: [
            {
                "normalized_pin": "6123001",
                "parcel_id": "p",
                "source_record_id": "s",
                "locator": {"feature": 1},
            }
        ]
    }
    result = docs.covered_site(site, coverage, "gis-run")
    assert result["parcel_id"] == "p"
    assert result["address_sources"][0]["locator"]["object_id"] == 2


def test_opposing_polygon_at_another_primary_holds_site():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    site = {
        "street": "71 MAIN RD",
        "pin": "6123001",
        "primary": [{"oid": 2}, {"oid": 3}],
    }
    agree = {
        "normalized_pin": "6123001",
        "parcel_id": "p",
        "source_record_id": "s",
        "locator": {"feature": 1},
    }
    other = {**agree, "normalized_pin": "6123002", "parcel_id": "q"}
    for coverage in (
        {2: [agree], 3: [other]},
        {2: [agree, other], 3: [agree]},
        {2: [agree], 3: [{**agree, "parcel_id": "different"}]},
    ):
        assert docs.covered_site(site, coverage, "run") is None


def test_hash_suite_keeps_building_and_qualifier():
    from cre.ingestion import gwinnett_plan_occupancy as docs

    rows = [{"address": "71 MAIN RD, #40"}, {"address": "71 OAK RD BLDG 3 #40-A"}]
    assert docs.address_hits(
        [
            "71 MAIN RD STE 40",
            "71 OAK RD 3 - 40-A",
            "71 OAK RD STE 40-A",
            "71 MAIN RD STE 4",
        ],
        rows,
    ) == [[rows[0]], [rows[1]], [], []]
