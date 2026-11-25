import csv
import hashlib
import json
import stat
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from cre.ingestion import gwinnett_lookup as lookup

# Generated IDs from a synthetic reimport. Release identity comes from its verified inputs.
SOURCES = {
    "gwinnett_parcels": {
        "run_id": "other-gis-uuid",
        "artifact_sha256": "7bc547068cfaea1d884f9819bc304dabb79872f9d5c254185753561d5b4222e0",
        "observed_on": "2026-11-20",
        "mapping_version": "2",
    },
    "gwinnett_assessor": {
        "run_id": "other-assessor-uuid",
        "artifact_sha256": "e0b1876679dcbfbbd659d2724ead39251662588dbd928b6ebe7c541b065ed7ca",
        "observed_on": "2026-11-22",
        "mapping_version": "2",
    },
}
GIS_RUN = SOURCES["gwinnett_parcels"]["run_id"]
ASSESSOR_RUN = SOURCES["gwinnett_assessor"]["run_id"]


@pytest.fixture
def fixture_db():
    # Exercise the candidate query itself against synthetic relational data.
    with create_engine("sqlite://").begin() as conn:
        for schema in ("core", "provenance", "staging"):
            conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
        for table in (
            "core.jurisdiction(id,county_fips)",
            "core.parcel(id,jurisdiction_id,parcel_state)",
            "core.parcel_geometry_version(parcel_id,source_record_id,is_current,normalized_pin,address)",
            "staging.gwinnett_situs_address(parcel_id,source_record_id,raw_address,source_field)",
            "provenance.source_record(id,run_id,locator)",
        ):
            conn.exec_driver_sql(f"CREATE TABLE {table}")
        conn.exec_driver_sql(
            "INSERT INTO core.jurisdiction VALUES(1,'13135'),(2,'99999')"
        )
        for i in range(1, 10):
            gis = f"g{i}"
            assess = f"a{i}"
            conn.exec_driver_sql(
                "INSERT INTO core.parcel VALUES(?,?,?)",
                (i, 2 if i == 6 else 1, "retired" if i == 5 else "active"),
            )
            conn.exec_driver_sql(
                "INSERT INTO core.parcel_geometry_version VALUES(?,?,?,?,?)",
                (
                    i,
                    gis,
                    i != 7,
                    f"PIN{i}",
                    {1: "41 MAIN RD #2", 3: "GIS ONLY"}.get(i, str(i)),
                ),
            )
            conn.exec_driver_sql(
                "INSERT INTO provenance.source_record VALUES(?,?,?),(?,?,?)",
                (
                    gis,
                    "previous" if i == 8 else GIS_RUN,
                    json.dumps({"feature": i}),
                    assess,
                    "previous" if i == 9 else ASSESSOR_RUN,
                    json.dumps(
                        {"workbook": lookup.OWNER, "sheet": "Sheet1", "row": i + 1}
                    ),
                ),
            )
            street = {2: "41 Main Rd #3", 3: "33 Shared Ln", 4: "33 Shared Ln"}.get(
                i, " 41 Main Rd #2 "
            )
            conn.exec_driver_sql(
                "INSERT INTO staging.gwinnett_situs_address VALUES(?,?,?,?)",
                (i, assess, street, "PROPERTYSTREET"),
            )
        yield conn


def test_both_address_sources_context_and_unique_parcel_identity(fixture_db):
    hits, other_unit, base, shared, gis_only = lookup.candidates(
        fixture_db,
        [" 41 mAin rd #2", "41 MAIN RD #3", "41 Main Rd", "33 shared ln", "gis only"],
        SOURCES,
    )
    assert [h["normalized_pin"] for h in hits] == ["PIN1"]
    assert hits[0]["pin_source"]["locator"] == {"feature": 1, "field": "PIN"}
    assert hits[0]["address_sources"] == [
        {
            "dataset": "gwinnett_parcels",
            "run_id": GIS_RUN,
            "source_record_id": "g1",
            "locator": {"feature": 1, "field": "ADDRESS"},
        },
        {
            "dataset": "gwinnett_assessor",
            "run_id": ASSESSOR_RUN,
            "source_record_id": "a1",
            "locator": {
                "workbook": lookup.OWNER,
                "sheet": "Sheet1",
                "row": 2,
                "field": "PROPERTYSTREET",
            },
        },
    ]
    assert [h["normalized_pin"] for h in other_unit] == ["PIN2"]
    assert not base
    assert [h["normalized_pin"] for h in shared] == ["PIN3", "PIN4"]
    assert [h["normalized_pin"] for h in gis_only] == ["PIN3"]


def write_labels(path, count=100):
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["county_fips", "address", "expected_pin", "source_case"])
        for i in range(count):
            writer.writerow(["13135", " 41 Main Rd #2 ", f"PIN-{i}", f"case-{i}"])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_frozen_cases_and_ambiguous_matches_count(tmp_path):
    labels = tmp_path / "labels.csv"
    digest = write_labels(labels)
    with pytest.raises(ValueError, match="digest"):
        lookup.load_labels(labels, "0" * 64)
    rows = lookup.load_labels(labels, digest)
    assert rows[0]["address"] == " 41 Main Rd #2 "
    hits = [[{"normalized_pin": f"PIN{i}"}] for i in range(100)]
    hits[0] = []
    hits[1].append({"normalized_pin": "ANOTHER"})
    hits[2] = [{"normalized_pin": "WRONG"}]
    summary, cases = lookup.evaluate(rows, hits)
    assert summary["count"] == 100
    assert summary["outcomes"] == {
        "correct": 97,
        "no_match": 1,
        "ambiguous": 1,
        "wrong_unique_pin": 1,
    }
    assert summary["passed"] is False
    assert cases[1]["expected_among_candidates"] is True
    assert cases[1]["candidate_count"] == 2
    hits[1].pop()
    assert lookup.evaluate(rows, hits)[0]["passed"] is True
    digest = write_labels(labels, 99)
    with pytest.raises(ValueError, match="100"):
        lookup.load_labels(labels, digest)


def test_output_is_private_atomic_and_preserves_existing_evidence(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "report.json"
    lookup.write_report(path, {"observed": 1}, root=private)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        lookup.write_report(path, {"observed": 2}, root=private)
    assert json.loads(path.read_text()) == {"observed": 1}
    (private / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PermissionError):
        lookup.write_report(private / "escape" / "outside.json", {}, root=private)
    assert not (tmp_path / "outside.json").exists()
    redirected_root = tmp_path / "redirect"
    redirected_root.symlink_to(private, target_is_directory=True)
    with pytest.raises(PermissionError):
        lookup.write_report(
            redirected_root / "redirected.json", {}, root=redirected_root
        )


@pytest.mark.parametrize(
    "key,unsafe",
    [
        ("gwinnett_parcels", "disabled"),
        ("gwinnett_assessor", "wrong_date"),
        ("gwinnett_parcels", "mapping"),
        ("gwinnett_parcels", "automatic"),
        ("gwinnett_assessor", "shared"),
        ("gwinnett_assessor", "wrong_digest"),
        ("gwinnett_assessor", "extra_publication"),
    ],
)
def test_pin_both_eligible_publications_and_manual_private_rights(key, unsafe):
    rows = []
    for name, source in SOURCES.items():
        manifest = json.loads((Path("contracts") / f"{name}.json").read_text())
        rows.append(
            {
                "dataset_key": name,
                "run_id": source["run_id"],
                "artifact_sha256": source["artifact_sha256"],
                "raw_object_key": source["artifact_sha256"],
                "manifest": manifest,
                "observed_on": date.fromisoformat(source["observed_on"]),
                "mapping_version": "2",
                "published_manifest": manifest,
                "enabled": True,
                "shared_display": False,
                "export_allowed": False,
            }
        )
    assert lookup.check_sources(rows) == SOURCES
    row = next(r for r in rows if r["dataset_key"] == key)
    if unsafe == "disabled":
        row["enabled"] = False
    elif unsafe == "wrong_date":
        row["observed_on"] = date(2026, 11, 17)
    elif unsafe == "mapping":
        row["mapping_version"] = "1"
    elif unsafe == "wrong_digest":
        row["raw_object_key"] = "another"
    elif unsafe == "automatic":
        row["manifest"]["rights"]["methods"].append("automatic")
    elif unsafe == "extra_publication":
        rows.append(dict(row, run_id="newer"))
    else:
        row["published_manifest"] = dict(
            row["manifest"], rights=dict(row["manifest"]["rights"], shared_display=True)
        )
    with pytest.raises((PermissionError, ValueError)):
        lookup.check_sources(rows)


def test_cli_accepts_independently_frozen_100_row_sample(tmp_path, monkeypatch):
    labels = tmp_path / "labels.csv"
    digest = write_labels(labels)
    report = tmp_path / "another-benchmark.json"

    def retrieve(addresses):
        # Permit keys are unavailable to the candidate retrieval function.
        assert addresses == [" 41 Main Rd #2 "] * 100
        return SOURCES, [[] for _ in addresses]

    monkeypatch.setattr(lookup, "fetch_candidates", retrieve)
    writer = lookup.write_report
    monkeypatch.setattr(
        lookup, "write_report", lambda path, data: writer(path, data, root=tmp_path)
    )
    assert (
        lookup.main(
            [
                "benchmark-addresses",
                str(labels),
                "--sha256",
                digest,
                "--output",
                str(report),
            ]
        )
        == 1
    )
    result = json.loads(report.read_text())
    assert result["sources"] == SOURCES
    assert result["labels_sha256"] == digest
    assert result["summary"]["count"] == 100
    assert len(result["cases"]) == 100


def test_private_address_point_lookup_and_scorer_use_the_same_mode(
    tmp_path, monkeypatch, capsys
):
    calls = []

    def retrieve(addresses, *, point_audit):
        calls.append(addresses)
        point_audit.extend([["unresolved point"] for _ in addresses])
        return SOURCES, [[] for _ in addresses]

    monkeypatch.setattr(lookup, "fetch_candidates", retrieve)
    writer = lookup.write_report
    monkeypatch.setattr(
        lookup, "write_report", lambda path, data: writer(path, data, root=tmp_path)
    )
    assert lookup.main(["lookup-address", "41 Main Rd", "--address-points"]) == 0
    assert json.loads(capsys.readouterr().out)["unresolved_address_points"] == [
        "unresolved point"
    ]
    labels = tmp_path / "labels.csv"
    digest = write_labels(labels)
    report = tmp_path / "result.json"
    assert (
        lookup.main(
            [
                "benchmark-addresses",
                str(labels),
                "--sha256",
                digest,
                "--output",
                str(report),
                "--address-points",
            ]
        )
        == 1
    )
    assert len(calls[0]) == 1 and len(calls[1]) == 100
    assert json.loads(report.read_text())["cases"][0]["unresolved_address_points"] == [
        "unresolved point"
    ]


def test_identity_mode_checks_points_and_retains_identity_review(
    tmp_path, monkeypatch, capsys
):
    def retrieve(addresses, *, point_audit, identity_audit):
        count = len(addresses)
        point_audit.extend([[] for _ in addresses])
        identity_audit.extend(
            [[{"reason": "conflicting child PINs"}] for _ in addresses]
        )
        return SOURCES, [[] for _ in range(count)]

    monkeypatch.setattr(lookup, "fetch_candidates", retrieve)
    writer = lookup.write_report
    monkeypatch.setattr(
        lookup, "write_report", lambda path, data: writer(path, data, root=tmp_path)
    )
    assert lookup.main(["lookup-address", "47 Example Rd", "--parcel-identities"]) == 0
    single = json.loads(capsys.readouterr().out)
    assert single["unresolved_address_points"] == []
    assert single["unresolved_parcel_identities"] == [
        {"reason": "conflicting child PINs"}
    ]
    labels = tmp_path / "labels.csv"
    report = tmp_path / "score.json"
    digest = write_labels(labels)
    assert (
        lookup.main(
            [
                "benchmark-addresses",
                str(labels),
                "--sha256",
                digest,
                "--output",
                str(report),
                "--parcel-identities",
            ]
        )
        == 1
    )
    assert (
        json.loads(report.read_text())["cases"][0]["unresolved_parcel_identities"]
        == single["unresolved_parcel_identities"]
    )
