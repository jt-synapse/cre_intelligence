from pathlib import Path

import pytest


def test_private_content_addressed_storage(tmp_path, monkeypatch):
    from cre.storage import get_bytes, put_bytes

    monkeypatch.delenv("CRE_S3_BUCKET", raising=False)
    monkeypatch.setenv("CRE_STORAGE_DIR", str(tmp_path))
    key = put_bytes(b"fixture")
    assert put_bytes(b"fixture") == key
    assert get_bytes(key) == b"fixture"
    with pytest.raises(ValueError):
        get_bytes("../fixture")
    assert len([p for p in Path(tmp_path).rglob("*") if p.is_file()]) == 1


def test_demo_disabled_by_default(monkeypatch):
    from fastapi import HTTPException

    from cre.auth import identify

    monkeypatch.delenv("CRE_DEMO_MODE", raising=False)
    with pytest.raises(HTTPException):
        identify("Bearer local-demo")


def test_oidc_signature_issuer_audience_and_expiry(monkeypatch):
    import time
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi import HTTPException

    from cre import auth

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("CRE_OIDC_ISSUER", "https://identity.example.test")
    monkeypatch.setenv("CRE_OIDC_JWKS_URL", "https://identity.example.test/keys")
    monkeypatch.setenv("CRE_OIDC_AUDIENCE", "cre-test")
    monkeypatch.setattr(
        auth,
        "_keys",
        lambda url: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(
                key=private.public_key()
            )
        ),
    )
    fields = {
        "sub": "researcher",
        "aud": "cre-test",
        "iss": "https://identity.example.test",
        "exp": int(time.time()) + 60,
    }

    def bearer(payload, key=private):
        return "Bearer " + jwt.encode(payload, key, algorithm="RS256")

    assert auth.identify(bearer(fields)) == "researcher"
    for change in (
        {"aud": "another-service"},
        {"iss": "https://other.test"},
        {"exp": 0},
    ):
        with pytest.raises(HTTPException) as exc:
            auth.identify(bearer(fields | change))
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        auth.identify(
            bearer(
                fields, rsa.generate_private_key(public_exponent=65537, key_size=2048)
            )
        )


def test_production_disables_demo(monkeypatch):
    from cre.auth import demo_enabled

    monkeypatch.setenv("CRE_ENV", "production")
    monkeypatch.setenv("CRE_DEMO_MODE", "true")
    assert demo_enabled() is False
