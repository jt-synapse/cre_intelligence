"""Pin the exact parcel geometry references and exportable layer observations in a dossier."""

from fastapi import HTTPException

from .records import one, rows

KINDS = ("environmental", "flood", "zoning")


def screening_snapshot(conn, prop):
    result = rows(
        conn,
        """
        WITH parcels AS (
            SELECT DISTINCT v.id,v.source_record_id,v.content_sha256,v.geom,v.attribution
            FROM core.visible_parcel v JOIN core.property_parcel pp ON pp.parcel_id=v.id
            WHERE pp.valid_to IS NULL AND core.current_property_id(pp.property_id)=:prop AND v.export_allowed
        ), layers AS (
            SELECT l.*, e.content_sha256 FROM core.visible_screening_layer l
            JOIN core.exportable_screening_version e ON e.id=l.id WHERE l.export_allowed
        )
        SELECT p.id AS parcel_id,p.source_record_id AS geometry_source_id,p.content_sha256 AS geometry_sha256,
               p.attribution AS geometry_attribution,k.kind,l.id AS layer_id,l.dataset_key,l.reference,l.observed_on,
               l.content_sha256,f.label,f.locator,CASE WHEN f.id IS NOT NULL THEN 'matched'
               WHEN ST_Covers(l.coverage,p.geom) THEN 'no_match' ELSE 'unknown' END AS status
        FROM parcels p CROSS JOIN (VALUES ('environmental'),('flood'),('zoning')) k(kind)
        LEFT JOIN layers l ON l.kind=k.kind
        LEFT JOIN core.visible_screening_feature f ON f.layer_id=l.id AND ST_Intersects(f.geom,p.geom)
        ORDER BY p.id,k.kind,l.dataset_key,f.locator """,
        prop=prop,
    )
    return result or [
        {"kind": kind, "status": "unknown", "layer_id": None} for kind in KINDS
    ]


def check_screening(conn, results):
    for row in results:
        if row.get("geometry_source_id") and not one(
            conn,
            """
              SELECT 1 FROM provenance.visible_source_record WHERE source_record_id=:source AND export_allowed
                  AND attribution IS NOT DISTINCT FROM cast(:credit as text)""",
            source=row["geometry_source_id"],
            credit=row.get("geometry_attribution"),
        ):
            raise HTTPException(403, "Screening geometry export permission unavailable")
        if row["layer_id"] and not one(
            conn,
            """SELECT 1 FROM core.exportable_screening_version
                   WHERE id=:id AND content_sha256=:hash""",
            id=row["layer_id"],
            hash=row["content_sha256"],
        ):
            raise HTTPException(403, "Screening layer export permission unavailable")


def render_screening(results, line):
    line("Site and development screening", True)
    descriptions = {
        "matched": "Mapped feature intersects the parcel",
        "no_match": "No intersecting feature within documented coverage",
        "unknown": "Coverage unconfirmed or no exportable layer",
    }
    for row in results:
        line(f"{row['kind'].title()}: {descriptions[row['status']]}")
        if row.get("parcel_id"):
            line(
                f"Parcel {row['parcel_id']}, geometry reference {row['geometry_source_id']}"
            )
            if row.get("geometry_attribution"):
                line(f"Geometry attribution: {row['geometry_attribution']}")
        if row.get("layer_id"):
            line(f"{row['dataset_key']} ({row['observed_on']}) / {row['reference']}")
            if row.get("label"):
                line(f"{row['label']} / {row['locator']}")
            line(f"Layer {row['layer_id']} / SHA-256 {row['content_sha256']}")
