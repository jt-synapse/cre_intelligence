"""Trusted source configuration and format-aware staging of operator-supplied snapshots."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fnmatch import fnmatchcase
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Literal
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, Field, model_validator

PRIVATE_GWINNETT_DATASETS = frozenset({"gwinnett_parcels", "gwinnett_assessor"})


class SnapshotError(ValueError):
    """The artifact requires review before any row can publish."""


class Rights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending_review", "approved", "disabled"]
    methods: list[Literal["manual", "automatic"]]
    retain_original: bool
    shared_display: bool
    export_allowed: bool
    basis: str = Field(min_length=1)
    attribution: str
    retention: str = Field(min_length=1)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str = Field(pattern=r"^[a-z0-9_]+$")
    dataset_key: str = Field(pattern=r"^[a-z0-9_]+$")
    publisher: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    cadence: str
    county_fips: str = Field(pattern=r"^[0-9]{5}$")
    county_name: str
    state_code: str
    kind: Literal["parcels", "assessor"]
    mapping_version: str = Field(min_length=1)
    rights: Rights
    columns: dict[str, str]
    known_columns: list[str]
    join_identifier: Literal["pin", "taxpin", "lrsn"] = "pin"
    join_dataset: str | None = None
    worksheets: list[str] = []
    workbook_patterns: list[str] = ["*.xlsx"]
    archive_companions: list[str] = []
    reader_release: str | None = Field(default=None, min_length=1, max_length=128)
    paired_datasets: list[str] = []
    expected_snapshot_rows: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def mapping(self):
        if self.archive_companions:
            names = self.workbook_patterns + self.archive_companions
            if (
                self.kind != "assessor"
                or not self.workbook_patterns
                or len(names) != len(set(names))
                or any(
                    not name.lower().endswith(".xlsx") or any(c in name for c in "*?[]")
                    for name in names
                )
            ):
                raise ValueError(
                    "archive mappings require distinct, exact XLSX member names"
                )
        if self.join_identifier != "pin" and (
            self.kind != "assessor" or not self.join_dataset
        ):
            raise ValueError(
                "alternate assessor join requires a confirmed GIS dataset key"
            )
        if set(self.columns.values()) - set(self.known_columns):
            raise ValueError("each mapped column must be in known_columns")
        if self.rights.status == "approved":
            required = {"pin", "owner"} if self.kind == "assessor" else {"pin"}
            if not required.issubset(self.columns) or (
                self.kind == "assessor" and not self.worksheets
            ):
                raise ValueError("approved source requires an inspected mapping")
        return self

    def authorize(self, method: str):
        if (
            self.rights.status != "approved"
            or method not in self.rights.methods
            or not self.rights.retain_original
        ):
            raise PermissionError(
                f"{self.dataset_key} does not authorize retained {method} import"
            )


@dataclass(frozen=True)
class Row:
    fields: dict[str, Any]
    locator: dict[str, Any]
    external_id: str
    source_payload: Any
    geometry: Any = None
    srid: int | None = None
    error: str | None = None

    def digest(self) -> str:
        content = [self.source_payload, self.srid]
        return sha256(
            json.dumps(
                content,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


def normalize_pin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("PIN must retain its source text")
    return re.sub(r"[-\s]+", "", value.strip().upper())


def _headers(names, manifest):
    unknown = set(names) - set(manifest.known_columns)
    required = (
        manifest.known_columns
        if manifest.archive_companions
        else manifest.columns.values()
    )
    missing = set(required) - set(names)
    if unknown or missing:
        raise SnapshotError(
            f"mapping review: unknown headers {sorted(unknown)}, missing {sorted(missing)}"
        )


def _scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fields(record, manifest):
    fields = {key: _scalar(record.get(col)) for key, col in manifest.columns.items()}
    if (
        manifest.kind == "assessor"
        and manifest.join_identifier == "lrsn"
        and type(fields.get("pin")) is int
    ):
        fields["pin"] = str(fields["pin"])
    for key, value in fields.items():
        if value is None:
            continue
        if key in (
            "taxpin",
            "pin",
            "owner",
            "owner_line_2",
            "address",
            "mailing_address",
            "mailing_state",
            "global_id",
        ):
            if not isinstance(value, str):
                raise SnapshotError(
                    f"mapping review: {manifest.columns[key]} requires text"
                )
        if key in ("mailing_street", "mailing_city", "mailing_zip") and type(
            value
        ) not in (str, int):
            raise SnapshotError(
                f"mapping review: {manifest.columns[key]} requires source text or an integer"
            )
        if key in (
            "assessed_value",
            "deeded_acres",
            "gis_acres",
            "source_total_value",
            "source_tax_total",
        ) and (type(value) not in (int, float) or not math.isfinite(value)):
            raise SnapshotError(
                f"mapping review: {manifest.columns[key]} requires a finite number"
            )
        if (
            key in ("tax_year", "lrsn", "source_lrsn", "object_id")
            and type(value) is not int
        ):
            raise SnapshotError(
                f"mapping review: {manifest.columns[key]} requires an integer"
            )
    return fields


def _row_error(fields):
    if not normalize_pin(fields.get("pin") or ""):
        return "missing PIN"
    for key in ("assessed_value", "deeded_acres", "gis_acres"):
        if fields.get(key) is not None and fields[key] < 0:
            return f"negative {key}"
    return None


def _geojson(manifest, data):
    obj = json.loads(
        data,
        parse_constant=lambda v: (_ for _ in ()).throw(
            SnapshotError("nonfinite JSON value")
        ),
    )
    if (
        not isinstance(obj, dict)
        or obj.get("type") != "FeatureCollection"
        or not isinstance(obj.get("features"), list)
    ):
        raise SnapshotError("expected a GeoJSON FeatureCollection")
    crs = obj.get("crs")
    srid = 4326  # RFC 7946 fixes the default for an unlabelled GeoJSON artifact.
    if crs is not None:
        try:
            name = crs["properties"]["name"]
        except (TypeError, KeyError) as exc:
            raise SnapshotError("unrecognized artifact CRS") from exc
        if isinstance(name, str) and name.upper().endswith("CRS84"):
            srid = 4326
        else:
            match = re.fullmatch(
                r"(?:urn:ogc:def:crs:EPSG::|EPSG:)([0-9]+)", str(name), re.IGNORECASE
            )
            if not match or int(match.group(1)) not in (2240, 4326):
                raise SnapshotError("unsupported artifact CRS")
            srid = int(match.group(1))
    rows = []
    for ordinal, feature in enumerate(obj["features"]):
        if (
            not isinstance(feature, dict)
            or feature.get("type") != "Feature"
            or not isinstance(feature.get("properties"), dict)
        ):
            raise SnapshotError(f"malformed GeoJSON feature {ordinal}")
        props = feature["properties"]
        _headers(props.keys(), manifest)
        fields = _fields(props, manifest)
        external_id = (
            fields.get("global_id") or fields.get("pin") or f"feature:{ordinal}"
        )
        rows.append(
            Row(
                fields,
                {"feature": ordinal},
                str(external_id),
                feature,
                feature.get("geometry"),
                srid,
                _row_error(fields),
            )
        )
    return rows


def _archive(data):
    archive = ZipFile(BytesIO(data))
    # Never extract to disk. Limit both nested XLSX members and outer ZIP members.
    members = archive.infolist()
    if len(members) > 10000 or sum(i.file_size for i in members) > 1024**3:
        archive.close()
        raise SnapshotError("workbook archive exceeds the inspection limit")
    return archive


def _books(data, manifest=None):
    with _archive(data) as archive:
        if manifest and manifest.archive_companions:
            names = [i.filename for i in archive.infolist() if not i.is_dir()]
            expected = set(manifest.workbook_patterns + manifest.archive_companions)
            if len(names) != len(expected) or set(names) != expected:
                raise SnapshotError(
                    "mapping review: workbook archive inventory changed"
                )
            for name in manifest.workbook_patterns:
                yield name, archive.read(name)
            return
        if "[Content_Types].xml" in archive.namelist():
            yield None, data
            return
        members = sorted(
            i.filename
            for i in archive.infolist()
            if i.filename.lower().endswith(".xlsx") and not i.is_dir()
        )
        if not members:
            raise SnapshotError("archive contains no XLSX workbooks")
        for name in members:
            yield name, archive.read(name)


def _open_book(payload):
    with _archive(payload):
        return load_workbook(
            BytesIO(payload), read_only=True, data_only=True, keep_links=False
        )


def inspect_workbook(data):
    result = []
    for name, payload in _books(data):
        book = _open_book(payload)
        try:
            for sheet in book:
                header = next(sheet.values, ())
                result.append(
                    {"workbook": name, "sheet": sheet.title, "headers": list(header)}
                )
        finally:
            book.close()
    return result


def _assessor_rows(manifest: Manifest, data: bytes):
    sheets_seen = set()
    for name, payload in _books(data, manifest):
        if name and not any(
            fnmatchcase(name, p) or fnmatchcase(PurePosixPath(name).name, p)
            for p in manifest.workbook_patterns
        ):
            raise SnapshotError(f"mapping review: unexpected workbook {name}")
        book = _open_book(payload)
        try:
            for sheet in book:
                if sheet.title not in manifest.worksheets:
                    raise SnapshotError(
                        f"mapping review: unexpected sheet {sheet.title}"
                    )
                sheets_seen.add(sheet.title)
                iterator = iter(sheet.values)
                headers = list(next(iterator, ()))
                while headers and headers[-1] is None:
                    headers.pop()
                if not all(isinstance(h, str) for h in headers) or len(headers) != len(
                    set(headers)
                ):
                    raise SnapshotError(
                        "mapping review: invalid or duplicate workbook headers"
                    )
                _headers(headers, manifest)
                for ordinal, values in enumerate(iterator, 2):
                    if all(v is None for v in values):
                        continue
                    if any(v is not None for v in values[len(headers) :]):
                        raise SnapshotError(
                            f"mapping review: extra values in row {ordinal}"
                        )
                    record = {
                        key: _scalar(value) for key, value in zip(headers, values)
                    }
                    fields = _fields(record, manifest)
                    locator = {"sheet": sheet.title, "row": ordinal}
                    if name:
                        locator["workbook"] = name
                    yield Row(
                        fields,
                        locator,
                        str(fields.get("pin") or f"row:{ordinal}"),
                        source_payload=[name, sheet.title, record],
                        error=_row_error(fields),
                    )
        finally:
            book.close()
    if sheets_seen != set(manifest.worksheets):
        raise SnapshotError("mapping review: expected sheets are missing")


def iter_assessor_rows(manifest: Manifest, data: bytes):
    """Yield source rows in order. Exhaust the iterator before committing a snapshot."""
    try:
        yield from _assessor_rows(manifest, data)
    except (BadZipFile, UnicodeError) as exc:
        raise SnapshotError(f"invalid assessor artifact: {exc}") from exc


def parse_snapshot(manifest: Manifest, data: bytes) -> list[Row]:
    try:
        return (
            _geojson(manifest, data)
            if manifest.kind == "parcels"
            else list(iter_assessor_rows(manifest, data))
        )
    except (BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid {manifest.kind} artifact: {exc}") from exc
