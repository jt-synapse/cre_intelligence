"""Acceptance against migrated PostGIS. Configure three local CRE_WORKFLOW_* test URLs."""

import hashlib
import io
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, text

from cre.admin import grant_runtime, provision
from cre.auth import identify
from cre.ingestion.demo import seed
from cre.main import make_app
from cre.workflows import worker
from cre.workflows.reports import render


@pytest.fixture()
def platform(monkeypatch, tmp_path):
    urls = [
        os.getenv("CRE_WORKFLOW_" + name + "_URL")
        for name in ("OWNER", "RUNTIME", "WORKER")
    ]
    if not all(urls):
        pytest.skip(
            "Set CRE_WORKFLOW_OWNER_URL, CRE_WORKFLOW_RUNTIME_URL and CRE_WORKFLOW_WORKER_URL"
        )
    owner, runtime, worker_url = urls
    admin_db = create_engine(owner)
    if not admin_db.url.database.endswith("_test"):
        pytest.fail("Use a dedicated database ending in _test")
    monkeypatch.setenv("CRE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("CRE_S3_BUCKET", raising=False)
    monkeypatch.setenv("CRE_RESEARCH_PROVIDER", "disabled")
    monkeypatch.setenv("DATABASE_URL", owner)
    seed(3)
    org, other, viewer = uuid4(), uuid4(), uuid4()
    subject = str(uuid4())
    runtime_name = create_engine(runtime).url.username
    worker_db = create_engine(worker_url)
    with admin_db.begin() as conn:
        grant_runtime(conn, runtime_name, False)
        grant_runtime(conn, worker_db.url.username, True)
        for tenant, role in ((org, "admin"), (other, "admin"), (viewer, "viewer")):
            provision(conn, tenant, "workflow test", subject, role)
        parcel = conn.scalar(
            text("SELECT id FROM core.visible_parcel WHERE county_fips='99001' LIMIT 1")
        )
    monkeypatch.setenv("DATABASE_URL", runtime)
    monkeypatch.setattr(worker, "engine", lambda: worker_db)
    app = make_app()
    app.dependency_overrides[identify] = lambda: subject
    with TestClient(app) as client:
        client.headers["X-Organization-ID"] = str(org)
        response = client.post("/v1/workspace/saves", json={"parcel_id": str(parcel)})
        assert response.is_success, response.text
        yield client, response.json()["property_id"], org, other, viewer
    admin_db.dispose()
    worker_db.dispose()


def submit(client, path, data, code=None):
    res = client.post("/v1/" + path, json=data)
    if code is None:
        assert res.is_success, (path, res.text)
    else:
        assert res.status_code == code, (path, res.text)
    return res.json()


def test_acquisition_to_reconstructible_export_and_tenant_revocation(platform):
    client, prop, org, other, viewer = platform
    doc = client.post(
        "/v1/documents",
        data={"property_id": prop, "kind": "filing", "exportable": "true"},
        files={
            "file": (
                "registry.txt",
                b"Company registration 102 states Example LLC. The property names Example LLC as asset manager. Company professional office: acquisitions@example.org.",
            )
        },
    ).json()
    case = submit(client, "investigations", {"property_id": prop})
    assert worker.run_once(org)
    detail = client.get(f"/v1/investigations/{case['id']}").json()
    assert detail["outcome"] == "unresolved" and len(detail["steps"]) >= 3
    casepath = f"investigations/{case['id']}"
    base = {
        "subject": "Example LLC",
        "reference": "Manual registry excerpt",
        "locator": "page 1",
        "document_id": doc["id"],
        "exportable": True,
    }
    identity = submit(
        client,
        casepath + "/evidence",
        dict(base, kind="entity_identity", assertion="Registered as 102"),
    )
    role = submit(
        client,
        casepath + "/evidence",
        dict(
            base,
            kind="property_role",
            assertion="Operating manager",
            relationship="asset_manager",
            identity_finding_id=identity["id"],
        ),
    )
    contact = submit(
        client,
        casepath + "/evidence",
        dict(
            base,
            kind="business_channel",
            assertion="Corporate email",
            channel_kind="business_email",
            channel_value="acquisitions@example.org",
            identity_finding_id=identity["id"],
        ),
    )
    submit(
        client,
        casepath + "/evidence",
        dict(
            base,
            subject="Other LLC",
            kind="property_role",
            assertion="Shared office",
            relationship="asset_manager",
            identity_finding_id=identity["id"],
        ),
        422,
    )
    weak = submit(
        client,
        casepath + "/evidence",
        {
            "subject": "Other LLC",
            "kind": "ownership",
            "assertion": "Claim without retained evidence",
            "reference": "Mentioned by broker",
            "locator": "phone",
        },
    )
    submit(
        client,
        casepath + "/reviews",
        {
            "finding_id": weak["id"],
            "decision": "accept",
            "reason": "No evidence retained",
        },
        422,
    )
    submit(
        client,
        casepath + "/reviews",
        {
            "finding_id": role["id"],
            "decision": "correct",
            "reason": "Correct role description",
            "correction": "Documented asset manager",
        },
    )
    assert client.get("/v1/entities/" + identity["id"]).status_code == 404
    assert not client.get("/v1/" + casepath).json()["graph"]["edges"]
    for item in (identity, role, contact):
        submit(
            client,
            casepath + "/reviews",
            {
                "finding_id": item["id"],
                "decision": "accept",
                "reason": "Reviewed source",
            },
        )
    assert (
        client.get("/v1/" + casepath).json()["outcome"] == "verified_business_contact"
    )
    graph = client.get("/v1/" + casepath).json()["graph"]
    assert {edge["relationship"] for edge in graph["edges"]} == {
        "asset_manager",
        "business_email",
    }
    assert all(edge["finding_id"] and edge["locator"] for edge in graph["edges"])
    assert (
        client.get("/v1/entities/" + identity["id"] + "/relationships").json()[
            "relationships"
        ]
        == graph["edges"]
    )
    assert client.get("/v1/properties/" + prop + "/ownership").json()["claims"]
    draft = submit(
        client,
        casepath + "/drafts",
        {"channel_finding_id": contact["id"], "body": "Who represents this site?"},
    )
    submit(
        client,
        "suppressions",
        {
            "property_id": prop,
            "channel": "Acquisitions@example.org",
            "reason": "Opted out",
        },
    )
    submit(
        client,
        f"drafts/{draft['id']}/reviews",
        {"decision": "approve", "reason": "reviewed"},
        409,
    )
    opp = submit(client, "opportunities", {"property_id": prop, "title": "Acquisition"})
    submit(
        client,
        f"opportunities/{opp['id']}/activities",
        {"kind": "task", "body": "Review basis", "assignee": "analyst"},
    )
    scenario = submit(
        client,
        "analysis-scenarios",
        {
            "property_id": prop,
            "name": "Base",
            "inputs": {
                "effective_gross_income": "100",
                "operating_expenses": "20",
                "property_value": "1000",
            },
        },
    )
    report = submit(
        client,
        "reports",
        {
            "property_id": prop,
            "scenario_id": scenario["id"],
            "investigation_id": case["id"],
            "opportunity_id": opp["id"],
        },
    )
    path = f"/v1/reports/{report['id']}"
    assert client.get(path + "/download").status_code == 409
    submit(
        client,
        "reports/" + report["id"] + "/reviews",
        {"decision": "approve", "reason": "Reviewed citations"},
    )
    assert worker.run_once(org)
    view = client.get(path).json()
    response = client.get(path + "/download")
    assert response.status_code == 200, response.text
    pdf = response.content
    text_content = " ".join(
        page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages
    )
    assert "Registry" in text_content or "registry" in text_content
    assert "Modeled scenario" in text_content
    assert (
        "Attribution" in text_content and "Synthetic demonstration data" in text_content
    )
    review = next(
        f
        for f in view["snapshot"]["investigation"]["reviewed_findings"]
        if f["id"] == role["id"]
    )
    assert review["current_assertion"] == "Documented asset manager"
    assert hashlib.sha256(render(view["snapshot"])).hexdigest() == view["pdf_hash"]
    assert pdf == render(view["snapshot"])
    client.headers["X-Organization-ID"] = str(other)
    for url in (
        path,
        path + "/download",
        "/v1/" + casepath,
        f"/v1/documents/{doc['id']}/download",
        f"/v1/entities/{identity['id']}/relationships",
        f"/v1/opportunities/{opp['id']}",
        f"/v1/analysis-scenarios/{scenario['id']}",
    ):
        assert client.get(url).status_code == 404, url
    assert client.get("/v1/opportunities").json() == []
    client.headers["X-Organization-ID"] = str(viewer)
    assert (
        client.post(
            "/v1/opportunities", json={"property_id": prop, "title": "denied"}
        ).status_code
        == 403
    )
    assert client.get("/v1/" + casepath).status_code == 403
    client.headers["X-Organization-ID"] = str(org)
    submit(client, "documents/" + doc["id"] + "/restrict", {})
    assert client.get(path).status_code == 403
    assert client.get(path + "/download").status_code == 403


def test_synthetic_research_contact_document_and_opportunity_benchmark(platform):
    client, prop, org, other, _ = platform
    docs = []
    for n in range(100):
        response = client.post(
            "/v1/documents",
            data={"property_id": prop, "kind": "deed" if n % 2 else "filing"},
            files={
                "file": (
                    f"reference-{n}.txt",
                    f"Synthetic filing {n}: Company {n}.".encode(),
                )
            },
        )
        assert response.status_code == 201, response.text
        docs.append(response.json()["id"])
    for n in range(30):
        case = submit(
            client,
            "investigations",
            {"property_id": prop, "objective": f"Review synthetic case {n}"},
        )
        path = f"investigations/{case['id']}"
        assert worker.run_once(org)
        if n % 3:
            item = submit(
                client,
                path + "/evidence",
                {
                    "subject": f"Company {n}",
                    "kind": "business_channel",
                    "assertion": "General inquiry line",
                    "channel_kind": "general_office",
                    "channel_value": f"office{n}@example.org",
                    "document_id": docs[n],
                    "reference": f"Filing {n}",
                    "locator": "line 1",
                },
            )
            if n % 3 == 2:
                submit(
                    client,
                    path + "/reviews",
                    {
                        "finding_id": item["id"],
                        "decision": "accept",
                        "reason": "Observed in filing",
                    },
                )
        result = client.get("/v1/" + path).json()
        assert (
            result["outcome"]
            == [
                "unresolved",
                "candidate_requires_review",
                "organizational_inquiry_route",
            ][n % 3]
        )
        assert result["status"] == "completed" and result["steps"]
        for finding in result["findings"]:
            assert (
                finding["document_id"] and finding["reference"] and finding["locator"]
            )
    for n in range(50):
        client.headers["X-Organization-ID"] = str(org if n % 2 else other)
        item = submit(
            client,
            "opportunities",
            {"property_id": prop, "title": f"Demo opportunity {n}"},
        )
        updated = client.patch(
            f"/v1/opportunities/{item['id']}",
            json={"stage": "research", "assignee": "analyst"},
        )
        assert updated.status_code == 200 and updated.json()["activities"]
    for tenant in (org, other):
        client.headers["X-Organization-ID"] = str(tenant)
        assert len(client.get("/v1/opportunities").json()) == 25


def test_failed_job_retry_is_scoped_and_does_not_duplicate_a_publication(
    platform, monkeypatch
):
    from cre.db import tenant_scope

    client, prop, org, other, _ = platform
    report = submit(client, "reports", {"property_id": prop})
    submit(
        client,
        f"reports/{report['id']}/reviews",
        {"decision": "approve", "reason": "Checked sources"},
    )
    job = client.get("/v1/jobs").json()[0]
    with monkeypatch.context() as fail:

        def unavailable(_):
            raise OSError("Synthetic storage outage")

        fail.setattr(worker, "put_bytes", unavailable)
        for _ in range(3):
            with worker.engine().begin() as conn:
                tenant_scope(conn, org)
                conn.execute(
                    text(
                        "UPDATE operations.workflow_job SET available_at=now() WHERE org_id=:org AND id=:id"
                    ),
                    {"org": org, "id": job["id"]},
                )
            assert worker.run_once(org)
    assert client.get(f"/v1/reports/{report['id']}").json()["status"] == "failed"
    client.headers["X-Organization-ID"] = str(other)
    submit(client, f"jobs/{job['id']}/retry", {}, 404)
    client.headers["X-Organization-ID"] = str(org)
    submit(client, f"jobs/{job['id']}/retry", {})
    assert worker.run_once(org)
    assert not worker.run_once(org)
    assert client.get(f"/v1/reports/{report['id']}/download").status_code == 200
    submit(client, f"jobs/{job['id']}/retry", {}, 409)


def test_research_provider_uses_only_approved_excerpts_and_retains_partial_case(
    platform, monkeypatch
):
    from cre.db import tenant_scope
    import httpx

    client, prop, org, _, _ = platform
    for n, allow in enumerate(("true", "false")):
        response = client.post(
            "/v1/documents",
            data={"property_id": prop, "allow_ai": allow},
            files={"file": (f"source-{n}.txt", f"Authorized flag {allow}.".encode())},
        )
        assert response.status_code == 201
    calls = []

    def unavailable(excerpts, tokens, id, meter):
        calls.append(excerpts)
        assert [d["text"] for d in excerpts] == ["Authorized flag true."]
        request = httpx.Request("POST", "https://example.org")
        raise httpx.HTTPStatusError(
            "Rate limit", request=request, response=httpx.Response(429, request=request)
        )

    monkeypatch.setenv("CRE_RESEARCH_PROVIDER", "openai")
    monkeypatch.setattr(worker, "extract_candidates", unavailable)
    case = submit(
        client,
        "investigations",
        {"property_id": prop, "max_external_requests": 1, "max_tokens": 4000},
    )
    assert worker.run_once(org)
    job = client.get("/v1/jobs").json()[0]
    with worker.engine().begin() as conn:
        tenant_scope(conn, org)
        conn.execute(
            text("UPDATE operations.workflow_job SET available_at=now() WHERE id=:id"),
            {"id": job["id"]},
        )
    assert worker.run_once(org)
    record = client.get(f"/v1/investigations/{case['id']}").json()
    assert record["outcome"] == "unresolved" and record["status"] == "completed"
    assert record["requests_used"] == 1 and len(calls) == 1
    assert any(
        s["name"] == "attempt_failed" and s["detail"]["http_status"] == 429
        for s in record["steps"]
    )


def test_disabled_shared_assessor_drops_entity_and_relationships(platform):
    client, prop, *_ = platform
    owner = create_engine(os.environ["CRE_WORKFLOW_OWNER_URL"])
    shared = client.get(f"/v1/properties/{prop}/ownership").json()["claims"]
    party = next(
        c["value"]["party_id"] for c in shared if c["dataset_key"] == "demo_assessor"
    )
    path = f"/v1/entities/{party}"
    assert client.get(path).json()["name"]
    assert client.get(path + "/relationships").json()["relationships"]
    try:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "UPDATE provenance.source_dataset SET enabled=false WHERE dataset_key='demo_assessor'"
                )
            )
        assert client.get(path).status_code == 404
        assert client.get(path + "/relationships").status_code == 404
        assert not client.get(f"/v1/properties/{prop}/ownership").json()["claims"]
    finally:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "UPDATE provenance.source_dataset SET enabled=true WHERE dataset_key='demo_assessor'"
                )
            )
        owner.dispose()


def test_model_candidates_can_be_typed_and_verified_without_reentering_evidence(
    platform, monkeypatch
):
    from cre.workflows.research import Extraction

    client, prop, org, other, _ = platform
    excerpt = "Example LLC is the property's named asset manager. Its office email is team@example.org."
    doc = client.post(
        "/v1/documents",
        data={"property_id": prop, "kind": "filing", "allow_ai": "true"},
        files={"file": ("manager.txt", excerpt.encode())},
    ).json()
    monkeypatch.setenv("CRE_RESEARCH_PROVIDER", "openai")

    def candidates(excerpts, budget, id, meter):
        assert excerpts[0]["text"] == excerpt
        return [
            Extraction(
                document_id=doc["id"],
                subject="Example LLC",
                kind=kind,
                assertion=assertion,
                quote=excerpt,
            )
            for kind, assertion in (
                ("entity_identity", "Company is Example LLC"),
                ("property_role", "Named asset manager"),
                ("business_channel", "Company office is team@example.org"),
            )
        ], 100

    monkeypatch.setattr(worker, "extract_candidates", candidates)
    case = submit(
        client,
        "investigations",
        {"property_id": prop, "max_external_requests": 1, "max_tokens": 4000},
    )
    assert worker.run_once(org)
    path = "investigations/" + case["id"]
    original = client.get("/v1/" + path).json()
    candidates = {f["kind"]: f for f in original["findings"]}
    identity, role, channel = [
        candidates[k]["id"]
        for k in ("entity_identity", "property_role", "business_channel")
    ]
    url = path + "/reviews"
    common = {
        "decision": "accept",
        "reason": "Reviewed the cited document and exact excerpt.",
    }
    submit(client, url, {**common, "finding_id": identity})
    submit(
        client,
        url,
        {
            **common,
            "finding_id": role,
            "enrichment": {
                "relationship": "asset_manager",
                "identity_finding_id": identity,
            },
        },
    )
    submit(
        client,
        url,
        {
            **common,
            "finding_id": channel,
            "enrichment": {"relationship": "asset_manager"},
        },
        422,
    )
    submit(
        client,
        url,
        {
            **common,
            "finding_id": channel,
            "enrichment": {
                "channel_kind": "business_email",
                "channel_value": "team@example.org",
                "identity_finding_id": identity,
            },
        },
    )
    case = client.get("/v1/" + path).json()
    assert case["outcome"] == "verified_business_contact" and len(case["findings"]) == 3
    assert all(
        f["method"] == "model_extraction"
        and f["source_excerpt"] == excerpt
        and f["document_id"] == doc["id"]
        for f in case["findings"]
    )
    assert case["reviews"][-1]["typed_evidence"]["identity_finding_id"] == identity
    submit(
        client, url, {"finding_id": channel, "decision": "stale", "reason": "Recheck"}
    )
    assert client.get("/v1/" + path).json()["outcome"] != "verified_business_contact"
    submit(client, url, {**common, "finding_id": channel})
    assert client.get("/v1/" + path).json()["outcome"] == "verified_business_contact"
    client.headers["X-Organization-ID"] = str(other)
    submit(
        client,
        url,
        {
            **common,
            "finding_id": channel,
            "enrichment": {"channel_value": "other@example.org"},
        },
        404,
    )


def test_screening_export_pins_coverage_and_survives_refresh_but_honors_revocation(
    platform,
):
    import json
    from datetime import date
    from cre.screening import Layer, publish

    client, prop, org, _, _ = platform
    owner = create_engine(os.environ["CRE_WORKFLOW_OWNER_URL"])
    key = "report-layer-" + str(uuid4())
    with owner.connect() as conn:
        geometry = conn.scalar(
            text("""SELECT ST_AsGeoJSON(ST_Expand(v.geom,0.00001)) FROM core.visible_parcel v
            JOIN core.property_parcel pp ON pp.parcel_id=v.id WHERE pp.property_id=:id LIMIT 1"""),
            {"id": prop},
        )
    polygon = json.loads(geometry)
    artifact = json.dumps({"type": "FeatureCollection", "features": []}).encode()

    def layer(when, *, allow=True, features=artifact):
        manifest = Layer(
            dataset_key=key,
            kind="zoning",
            reference="Synthetic zoning index",
            observed_on=when,
            rights_reference="Synthetic local fixture",
            permitted_manual_import=True,
            permitted_retention=True,
            shared_display=True,
            export_allowed=allow,
            label_field="code",
            coverage=polygon,
        )
        with owner.begin() as conn:
            return publish(conn, manifest, features)

    layer(date(2026, 1, 1))
    draft = submit(client, "reports", {"property_id": prop})
    path = f"/v1/reports/{draft['id']}"
    view = client.get(path).json()
    snapshot = view["snapshot"]
    assert snapshot["template"] == "cre-dossier-2"
    rows = snapshot["screening"]
    assert any(r.get("dataset_key") == key and r["status"] == "no_match" for r in rows)
    assert any(r["kind"] == "flood" and r["status"] == "unknown" for r in rows)
    submit(
        client,
        f"reports/{draft['id']}/reviews",
        {"decision": "approve", "reason": "Reviewed cited screening"},
    )
    assert worker.run_once(org)
    before = client.get(path + "/download").content
    text_content = " ".join(
        p.extract_text() for p in PdfReader(io.BytesIO(before)).pages
    )
    assert (
        "No intersecting feature within documented coverage" in text_content
        and "Synthetic zoning index" in text_content
    )
    features = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"code": "Z-A"}, "geometry": polygon}
            ],
        }
    ).encode()
    layer(date(2026, 2, 1), features=features)
    after = client.get(path + "/download")
    assert after.status_code == 200 and after.content == before == render(snapshot)
    second = submit(client, "reports", {"property_id": prop})
    view2 = client.get(f"/v1/reports/{second['id']}").json()["snapshot"]
    assert any(
        r.get("dataset_key") == key
        and r["status"] == "matched"
        and r["locator"] == "features[0]"
        for r in view2["screening"]
    )
    submit(
        client,
        f"reports/{second['id']}/reviews",
        {"decision": "approve", "reason": "Checked updated layer"},
    )
    layer(date(2026, 3, 1), allow=False)
    assert (
        client.get(path).status_code == 403
        and client.get(path + "/download").status_code == 403
    )
    assert worker.run_once(org)
    assert client.get(f"/v1/reports/{second['id']}/download").status_code != 200
    legacy = {k: v for k, v in snapshot.items() if k != "screening"}
    legacy["template"] = "cre-dossier-1"
    text_v1 = " ".join(
        p.extract_text() for p in PdfReader(io.BytesIO(render(legacy))).pages
    )
    assert "Site and development screening" not in text_v1
    owner.dispose()
