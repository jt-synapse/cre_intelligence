import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy import Connection, text

from cre.db import engine, tenant_scope


def demo_enabled():
    return (
        os.getenv("CRE_DEMO_MODE", "").lower() == "true"
        and os.getenv("CRE_ENV") != "production"
    )


@lru_cache(maxsize=4)
def _keys(url: str):
    return PyJWKClient(url, timeout=5)


def identify(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
        )
    token = authorization[7:]
    if demo_enabled() and token == "local-demo":
        return "local-demo-user"
    issuer, audience, jwks = (
        os.getenv(k, "")
        for k in ("CRE_OIDC_ISSUER", "CRE_OIDC_AUDIENCE", "CRE_OIDC_JWKS_URL")
    )
    if (
        not issuer.startswith("https://")
        or not jwks.startswith("https://")
        or not audience
    ):
        raise HTTPException(401, "Token verification is not configured")
    try:
        key = _keys(jwks).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError("Missing subject")
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired credential") from None
    return claims["sub"]


def bind_subject(conn: Connection, subject: str):
    unsafe = conn.scalar(
        text("""select rolsuper or rolbypassrls or pg_has_role(current_user,
        (select relowner from pg_class where oid='operations.organization'::regclass),'MEMBER')
        from pg_roles where rolname=current_user""")
    )
    if unsafe:
        raise RuntimeError("API credential must be a non-superuser without BYPASSRLS")
    conn.execute(text("select set_config('app.subject', :s, true)"), {"s": subject})


def memberships(conn: Connection, subject: str):
    return [
        dict(r)
        for r in conn.execute(
            text("""
        select m.org_id as id,o.name,m.role from operations.membership m
        join operations.organization o on o.id=m.org_id
        where m.subject=:s order by o.name,o.id
    """),
            {"s": subject},
        ).mappings()
    ]


@dataclass(frozen=True)
class Context:
    db: Connection
    org_id: UUID
    subject: str
    role: str

    def require(self, *roles):
        if self.role not in roles:
            raise HTTPException(403, "Insufficient workspace permissions")


def context(
    request: Request,
    subject: Annotated[str, Depends(identify)],
    x_organization_id: Annotated[UUID | None, Header()] = None,
):
    with engine().begin() as conn:
        if request.method in {"GET", "HEAD"}:
            # These existing downloads commit an access receipt before returning bytes.
            # Use the matched route template, never a caller-supplied path or header.
            audited_download = request.scope["route"].path in {
                "/v1/documents/{id}/download",
                "/v1/reports/{id}/download",
            }
            if audited_download:
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            else:
                conn.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
        bind_subject(conn, subject)
        rows = memberships(conn, subject)
        if x_organization_id is None and len(rows) > 1:
            raise HTTPException(400, "Select a workspace with X-Organization-ID")
        row = next(
            (r for r in rows if not x_organization_id or r["id"] == x_organization_id),
            None,
        )
        if not row:
            raise HTTPException(403, "Workspace membership required")
        tenant_scope(conn, row["id"])
        yield Context(conn, row["id"], subject, row["role"])


def audit(
    ctx: Context, action: str, resource_id: str | UUID, detail: dict | None = None
):
    ctx.db.execute(
        text("""
        insert into operations.audit_event(org_id,subject,action,resource_id,detail)
        values(:org,:subject,:action,:resource,cast(:detail as jsonb))
    """),
        {
            "org": ctx.org_id,
            "subject": ctx.subject,
            "action": action,
            "resource": str(resource_id),
            "detail": json.dumps(detail or {}, default=str),
        },
    )
