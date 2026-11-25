"""Deterministic fictional records in a dedicated demonstration jurisdiction."""

import json
from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from .contract import Manifest


def parcel_bytes(count=3):
    features = []
    for i in range(count):
        x, y = -84.01 + (i % 40) * 0.002, 33.95 + (i // 40) * 0.002
        # The three additional field-visit parcels fill gaps between the original fixtures.
        if 3 <= i < 6:
            x = -84.009 + (i - 3) * 0.002
        x, y = round(x, 6), round(y, 6)
        east, north = round(x + 0.001, 6), round(y + 0.001, 6)
        ring = [[x, y], [east, y], [east, north], [x, north], [x, y]]
        pin = f"{i + 1:04} A 001"
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "PIN": pin,
                    "TAXPIN": pin.replace(" ", "-"),
                    "LRSN": 10000 + i,
                    "GlobalID": f"synthetic-{i}",
                    "OBJECTID": i + 1,
                    "ADDRESS": f"{100 + i} Example Commerce Dr",
                    "DEEDEDACREAGE": 2.2,
                    "CALCULATEDACREAGE": 2.18,
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def assessor_bytes(count=3):
    out = BytesIO()
    book = Workbook()
    sheet = book.active
    sheet.title = "Assessment"
    sheet.append(
        ["Parcel Number", "Listed Owner", "Mailing Address", "Assessed Value", "Year"]
    )
    for i in range(count):
        name = (
            "Example Commerce Holdings LLC" if i % 2 == 0 else "Example Warehouse LLC"
        )
        sheet.append(
            [
                f"{i + 1:04} A 001",
                name,
                f"{501 + i} Example Plaza",
                225000 + i * 10000,
                2026,
            ]
        )
    book.save(out)
    return out.getvalue()


def seed(count=3):
    from .service import import_snapshot, register

    directory = Path(__file__).resolve().parents[2] / "contracts"
    reports = []
    for key, build in (
        ("demo_parcels", parcel_bytes),
        ("demo_assessor", assessor_bytes),
    ):
        register(Manifest.model_validate_json((directory / f"{key}.json").read_bytes()))
        reports.append(import_snapshot(key, build(count), date(2026, 1, 1)))
    return reports
