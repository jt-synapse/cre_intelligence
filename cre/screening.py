"""Publish a permitted WGS84 screening layer and its documented coverage."""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from cre.admin import admin_engine
from cre.storage import put_bytes


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_key: str = Field(min_length=1)
    kind: Literal["zoning", "environmental", "flood"]
    reference: str = Field(min_length=1)
    observed_on: date
    rights_reference: str = Field(min_length=1)
    permitted_manual_import: bool
    permitted_retention: bool
    shared_display: bool
    export_allowed: bool = False
    label_field: str = Field(min_length=1)
    # GeoJSON Polygon or MultiPolygon supplied by the source. Unknown extent is null.
    coverage: dict | None = None


def publish(conn, manifest: Layer, data: bytes):
    if not (manifest.permitted_manual_import and manifest.permitted_retention):
        raise PermissionError(
            "Retained manual screening imports require corresponding rights"
        )
    fc = json.loads(data)
    if (
        fc.get("type") != "FeatureCollection"
        or not isinstance(fc.get("features"), list)
        or "crs" in fc
    ):
        raise ValueError(
            "Expected a WGS84 GeoJSON FeatureCollection without a CRS override"
        )
    key = put_bytes(data)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,9))"),
        {"key": manifest.dataset_key},
    )
    existing = (
        conn.execute(
            text("""SELECT id,observed_on,object_key FROM core.screening_layer
        WHERE dataset_key=:dataset_key AND active"""),
            {"dataset_key": manifest.dataset_key},
        )
        .mappings()
        .first()
    )
    if existing and existing["observed_on"] > manifest.observed_on:
        raise ValueError("A newer layer is already active")
    conn.execute(
        text(
            "UPDATE core.screening_layer SET active=false WHERE dataset_key=:key AND active"
        ),
        {"key": manifest.dataset_key},
    )
    values = manifest.model_dump()
    values.update(
        key=key, coverage=json.dumps(manifest.coverage) if manifest.coverage else None
    )
    layer_id = conn.scalar(
        text("""INSERT INTO core.screening_layer(dataset_key,kind,reference,observed_on,
       object_key,rights_reference,shared_display,export_allowed,coverage)
       VALUES(:dataset_key,:kind,:reference,:observed_on,:key,:rights_reference,:shared_display,:export_allowed,
        ST_Multi(ST_GeomFromGeoJSON(cast(:coverage as text))))
       ON CONFLICT(dataset_key,observed_on,object_key) DO UPDATE SET active=true,
       shared_display=excluded.shared_display,export_allowed=excluded.export_allowed,rights_reference=excluded.rights_reference,
       reference=excluded.reference,coverage=excluded.coverage RETURNING id"""),
        values,
    )
    conn.execute(
        text("DELETE FROM core.screening_feature WHERE layer_id=:id"), {"id": layer_id}
    )
    for index, feature in enumerate(fc["features"]):
        label = feature["properties"].get(manifest.label_field)
        if label is None or not feature.get("geometry"):
            raise ValueError(f"Missing label or geometry on feature {index}")
        conn.execute(
            text("""INSERT INTO core.screening_feature(layer_id,label,locator,geom)
             VALUES(:id,:label,:locator,ST_GeomFromGeoJSON(cast(:geometry as text)))"""),
            {
                "id": layer_id,
                "label": str(label),
                "locator": f"features[{index}]",
                "geometry": json.dumps(feature["geometry"]),
            },
        )
    return layer_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("manifest", type=Path)
    imp.add_argument("artifact", type=Path)
    sub.add_parser("disable").add_argument("dataset_key")
    args = parser.parse_args()
    with admin_engine().begin() as conn:
        if args.action == "disable":
            conn.execute(
                text(
                    "UPDATE core.screening_layer SET active=false WHERE dataset_key=:k"
                ),
                {"k": args.dataset_key},
            )
        else:
            print(
                publish(
                    conn,
                    Layer.model_validate_json(args.manifest.read_bytes()),
                    args.artifact.read_bytes(),
                )
            )


if __name__ == "__main__":
    main()
