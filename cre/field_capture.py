"""Parcel field notes and photos, with immutable actor-scoped replay receipts."""

import hashlib
import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import text

from cre import storage
from cre.auth import audit
from cre.explorer import WRITERS, Access

router = APIRouter(prefix="/v1/parcels/{parcel_id}/field-captures")
PUBLIC = "id, parcel_id, note, photo_type, created_by, created_at"
PHOTO_LIMIT = 5 * 1024 * 1024


def require_parcel(ctx, parcel_id):
    if not ctx.db.scalar(
        text("SELECT 1 FROM core.visible_parcel WHERE id=:id"), {"id": parcel_id}
    ):
        raise HTTPException(404, "Parcel is unavailable")


def read_photo(photo, expected):
    if not photo:
        if expected:
            raise HTTPException(422, "Photo is missing")
        return None, None, None
    data = photo.file.read(PHOTO_LIMIT + 1)
    if len(data) > PHOTO_LIMIT:
        raise HTTPException(413, "Choose a photo under 5 MiB")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise HTTPException(422, "Photo checksum mismatch")
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > 50_000_000:
                raise HTTPException(422, "Photo exceeds 50 megapixels")
            media_type = Image.MIME[image.format]
            image.verify()
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        UnidentifiedImageError,
    ):
        raise HTTPException(422, "Choose a valid JPEG, PNG, or WebP photo") from None
    return data, digest, media_type


@router.post("")
def capture(
    parcel_id: UUID,
    ctx: Access,
    operation_id: Annotated[UUID, Form()],
    note: Annotated[str, Form(max_length=4000)] = "",
    photo_sha256: Annotated[str | None, Form(max_length=64)] = None,
    photo: Annotated[UploadFile | None, File()] = None,
):
    ctx.require(*WRITERS)
    require_parcel(ctx, parcel_id)
    data, digest, media_type = read_photo(photo, photo_sha256)
    note = note.strip()
    if not note and not data:
        raise HTTPException(422, "Add a note or a photo")
    params = {
        "org": ctx.org_id,
        "actor": ctx.subject,
        "operation": operation_id,
        "parcel": parcel_id,
        "note": note,
        "digest": digest,
        "media_type": media_type,
    }
    row = (
        ctx.db.execute(
            text(f"""INSERT INTO operations.field_capture
        (org_id, created_by, operation_id, parcel_id, note, object_key, photo_type)
        VALUES (:org, :actor, :operation, :parcel, :note, :digest, :media_type)
        ON CONFLICT (org_id, created_by, operation_id) DO NOTHING RETURNING {PUBLIC}"""),
            params,
        )
        .mappings()
        .first()
    )
    if row:
        # Other requests cannot observe the receipt until the immutable object exists.
        if data is not None and storage.put_bytes(data) != digest:
            raise OSError("Private storage checksum mismatch")
        audit(ctx, "field_capture.created", row["id"], {"parcel_id": parcel_id})
        return dict(row)
    previous = (
        ctx.db.execute(
            text(f"""SELECT {PUBLIC}, object_key FROM operations.field_capture
        WHERE org_id=:org AND created_by=:actor AND operation_id=:operation"""),
            params,
        )
        .mappings()
        .first()
    )
    if not previous or (
        previous["parcel_id"],
        previous["note"],
        previous["object_key"],
    ) != (parcel_id, note, digest):
        raise HTTPException(
            409, "This operation was already used for a different capture"
        )
    return {k: v for k, v in previous.items() if k != "object_key"}


@router.get("")
def captures(parcel_id: UUID, ctx: Access, offset: int = 0):
    require_parcel(ctx, parcel_id)
    if offset < 0:
        raise HTTPException(422, "Invalid offset")
    rows = (
        ctx.db.execute(
            text(f"""SELECT {PUBLIC} FROM operations.field_capture
        WHERE org_id=:org AND parcel_id=:parcel ORDER BY created_at DESC, id DESC
        LIMIT 51 OFFSET :offset"""),
            {"org": ctx.org_id, "parcel": parcel_id, "offset": offset},
        )
        .mappings()
        .all()
    )
    return {"items": [dict(row) for row in rows[:50]], "more": len(rows) > 50}


@router.get("/{capture_id}/photo")
def download_photo(parcel_id: UUID, capture_id: UUID, ctx: Access):
    row = (
        ctx.db.execute(
            text("""SELECT object_key, photo_type FROM operations.field_capture
        WHERE org_id=:org AND parcel_id=:parcel AND id=:id AND object_key IS NOT NULL"""),
            {"org": ctx.org_id, "parcel": parcel_id, "id": capture_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Photo is unavailable")
    return Response(
        storage.get_bytes(row["object_key"]),
        media_type=row["photo_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
