"""Field captures are atomic, scoped to a workspace, and replayable after a lost response."""

import hashlib
import io
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text

from cre.admin import provision
from cre.auth import identify
from cre.main import make_app


def test_field_routes_require_authentication():
    with TestClient(make_app()) as client:
        response = client.get(f"/v1/parcels/{uuid4()}/field-captures")
        assert response.status_code == 401


@pytest.fixture
def field_platform(monkeypatch, tmp_path):
    owner = os.getenv("CRE_WORKFLOW_OWNER_URL")
    runtime = os.getenv("CRE_WORKFLOW_RUNTIME_URL")
    if not owner or not runtime:
        pytest.skip("Requires the isolated workflow database")
    db = create_engine(owner)
    assert db.url.database.endswith("_test")
    monkeypatch.setenv("CRE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("CRE_S3_BUCKET", raising=False)
    monkeypatch.setenv("DATABASE_URL", runtime)
    tenant, other, actor, viewer = uuid4(), uuid4(), str(uuid4()), str(uuid4())
    with db.begin() as conn:
        for org, subject, role in [
            (tenant, actor, "analyst"),
            (other, actor, "admin"),
            (tenant, viewer, "viewer"),
        ]:
            provision(conn, org, "Field workspace", subject, role)
        parcel = conn.scalar(
            text("SELECT id FROM core.visible_parcel WHERE county_fips='99001' LIMIT 1")
        )
    assert parcel
    app = make_app()
    app.dependency_overrides[identify] = lambda: actor
    with TestClient(app) as client:
        client.headers["X-Organization-ID"] = str(tenant)
        yield client, f"/v1/parcels/{parcel}/field-captures", other, tenant, app, viewer
    db.dispose()


def photo():
    file = io.BytesIO()
    Image.new("RGB", (3, 3)).save(file, format="JPEG")
    return file.getvalue()


def test_retried_note_and_photo_have_one_receipt_and_authorized_read(field_platform):
    client, path, other, tenant, app, viewer = field_platform
    data = photo()
    payload = {
        "operation_id": str(uuid4()),
        "note": "Loading entrance",
        "photo_sha256": hashlib.sha256(data).hexdigest(),
    }
    files = {"photo": ("entrance.jpg", data, "image/jpeg")}
    first = client.post(path, data=payload, files=files)
    assert first.is_success, first.text
    replay = client.post(path, data=payload, files=files)
    assert replay.is_success and replay.json()["id"] == first.json()["id"]
    assert (
        client.post(
            path, data={**payload, "note": "different"}, files=files
        ).status_code
        == 409
    )
    rows = client.get(path).json()["items"]
    assert [row["note"] for row in rows] == ["Loading entrance"]
    photo_path = path + "/" + rows[0]["id"] + "/photo"
    assert client.get(photo_path).content == data
    assert "object_key" not in rows[0] and "photo_sha256" not in rows[0]
    client.headers["X-Organization-ID"] = str(other)
    assert client.get(path).json()["items"] == []
    assert client.get(photo_path).status_code == 404
    client.headers["X-Organization-ID"] = str(tenant)
    app.dependency_overrides[identify] = lambda: viewer
    assert client.get(photo_path).content == data
    assert client.post(path, data=payload, files=files).status_code == 403


def test_rejects_unavailable_parcel_empty_input_and_bad_photo(field_platform):
    client, path, *_ = field_platform
    operation = {"operation_id": str(uuid4()), "note": " "}
    assert client.post(path, data=operation).status_code == 422
    assert (
        client.post(
            f"/v1/parcels/{uuid4()}/field-captures", data={**operation, "note": "visit"}
        ).status_code
        == 404
    )
    for body, digest in [
        (photo(), "0" * 64),
        (b"not an image", hashlib.sha256(b"not an image").hexdigest()),
    ]:
        response = client.post(
            path,
            data={**operation, "photo_sha256": digest},
            files={"photo": ("bad.jpg", body, "image/jpeg")},
        )
        assert response.status_code == 422
    assert client.get(path).json()["items"] == []
