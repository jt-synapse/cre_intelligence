import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from cre.ingestion.contract import (
    Manifest,
    SnapshotError,
    normalize_pin,
    parse_snapshot,
)
from cre.ingestion.demo import assessor_bytes, parcel_bytes

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def manifest(name):
    return Manifest.model_validate_json((CONTRACTS / (name + ".json")).read_bytes())


def test_preserve_identifier_and_zeroes():
    rows = parse_snapshot(manifest("demo_parcels"), parcel_bytes())
    assert rows[0].fields["pin"] == "0001 A 001"
    assert normalize_pin(rows[0].fields["pin"]) == "0001A001"
    assert rows[0].srid == 4326


def test_county_permissions_limit_ingestion_to_private_manual_use():
    for name in ("gwinnett_parcels", "gwinnett_assessor"):
        source = manifest(name)
        source.authorize("manual")
        assert source.rights.retain_original
        assert not source.rights.shared_display
        assert not source.rights.export_allowed
        with pytest.raises(PermissionError):
            source.authorize("automatic")


def test_actual_artifact_crs_and_schema_drift():
    raw = json.loads(parcel_bytes())
    raw["crs"] = {"type": "name", "properties": {"name": "EPSG:2240"}}
    assert (
        parse_snapshot(manifest("demo_parcels"), json.dumps(raw).encode())[0].srid
        == 2240
    )
    raw["features"][0]["properties"]["NEW_COLUMN"] = 3
    with pytest.raises(SnapshotError, match="mapping review"):
        parse_snapshot(manifest("demo_parcels"), json.dumps(raw).encode())


def test_workbook_field_types_and_row_locator():
    rows = parse_snapshot(manifest("demo_assessor"), assessor_bytes())
    assert rows[0].fields["pin"] == "0001 A 001"
    assert rows[0].fields["owner"] == "Example Commerce Holdings LLC"
    assert rows[0].locator["sheet"] == "Assessment"
    assert rows[0].locator["row"] == 2


def test_mixed_archive_maps_only_the_declared_table_and_checks_all_member_names():
    source = manifest("demo_assessor")
    source.workbook_patterns = ["release/ownership.xlsx"]
    source.archive_companions = ["release/layout.xlsx"]
    payload = assessor_bytes(1)

    def archive(names):
        stream = BytesIO()
        with ZipFile(stream, "w") as out:
            for name in names:
                out.writestr(name, payload)
        return stream.getvalue()

    expected = source.workbook_patterns + source.archive_companions
    rows = parse_snapshot(source, archive(expected))
    assert len(rows) == 1
    assert rows[0].locator == {"workbook": expected[0], "sheet": "Assessment", "row": 2}
    for changed in [
        source.workbook_patterns,
        expected + ["NOTICE.txt"],
        ["ownership.xlsx", expected[1]],
    ]:
        with pytest.raises(SnapshotError, match="archive inventory changed"):
            parse_snapshot(source, archive(changed))
    with pytest.raises(SnapshotError, match="archive inventory changed"):
        parse_snapshot(source, payload)
    source.known_columns.append("First recorded in the original layout")
    with pytest.raises(SnapshotError, match="missing"):
        parse_snapshot(source, archive(expected))


def test_whole_record_fingerprint_covers_unmapped_source_fields():
    cfg = manifest("demo_parcels")
    cfg.known_columns.append("LOT")
    original = json.loads(parcel_bytes(1))
    original["features"][0]["properties"]["LOT"] = "A"
    first = parse_snapshot(cfg, json.dumps(original).encode())[0]
    original["features"][0]["properties"]["LOT"] = "B"
    second = parse_snapshot(cfg, json.dumps(original).encode())[0]
    assert first.digest() != second.digest()
