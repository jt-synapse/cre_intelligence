"""A dossier is an immutable snapshot and an approved rendering of that snapshot."""

import hashlib
import io
import json
from textwrap import wrap

from fastapi import HTTPException
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from .records import findings, one, property_claims, required
from .research import content_digest, outcome_for

from .site import screening_snapshot, check_screening, render_screening

TEMPLATE = "cre-dossier-2"


def public_finding(f):
    fields = (
        "id",
        "kind",
        "subject",
        "current_assertion",
        "state",
        "reference",
        "locator",
        "source_hash",
        "document_id",
        "review_id",
        "review_version",
        "effective_date",
        "relationship",
        "channel_kind",
        "channel_value",
        "identity_finding_id",
        "source_excerpt",
    )
    return {k: f[k] for k in fields}


def snapshot(conn, org, prop, request):
    claims = property_claims(conn, prop, export_only=True)
    result = {
        "template": TEMPLATE,
        "property_id": prop,
        "claims": claims,
        "screening": screening_snapshot(conn, prop),
    }
    for name, table in (
        ("scenario", "analysis_scenario"),
        ("opportunity", "opportunity"),
        ("investigation", "investigation"),
    ):
        id = getattr(request, name + "_id")
        if id is None:
            continue
        row = required(conn, table, org, id)
        if not one(
            conn,
            "SELECT core.current_property_id(:id)=:prop AS ok",
            id=row["property_id"],
            prop=prop,
        )["ok"]:
            raise HTTPException(
                422, "Report inputs must belong to the selected property"
            )
        if name == "investigation":
            permitted = []
            for item in findings(conn, org, id):
                if (
                    item["state"] not in {"verified", "conflicted"}
                    or not item["exportable"]
                ):
                    continue
                if (
                    item["document_id"]
                    and not required(conn, "document", org, item["document_id"])[
                        "exportable"
                    ]
                ):
                    continue
                permitted.append(public_finding(item))
            # Recompute the public conclusion solely from findings licensed for this report.
            result[name] = {
                "id": id,
                "reviewed_findings": permitted,
                "exportable_outcome": outcome_for(permitted, row["preferred_roles"]),
            }
        elif name == "scenario":
            result[name] = {
                k: row[k]
                for k in (
                    "id",
                    "name",
                    "assumptions",
                    "model_version",
                    "inputs",
                    "outputs",
                    "period",
                    "currency",
                    "sources",
                )
            }
        else:
            result[name] = {k: row[k] for k in ("id", "title", "stage", "assignee")}
    return json.loads(json.dumps(result, default=str))


def check_entitlements(conn, org, snapshot):
    check_screening(conn, snapshot.get("screening", []))
    for c in snapshot["claims"]:
        if not one(
            conn,
            """SELECT 1 FROM evidence.visible_claim
                    WHERE id=:id AND source_record_id=:source AND export_allowed
                    AND (NOT :has_credit OR attribution IS NOT DISTINCT FROM cast(:credit as text))""",
            has_credit="attribution" in c,
            credit=c.get("attribution"),
            id=c["id"],
            source=c["source_record_id"],
        ):
            raise HTTPException(403, "Source export permission unavailable")
    for item in snapshot.get("investigation", {}).get("reviewed_findings", []):
        if (
            item["document_id"]
            and not required(conn, "document", org, item["document_id"])["exportable"]
        ):
            raise HTTPException(403, "Document export permission unavailable")


def render(snapshot):
    if snapshot["template"] not in {"cre-dossier-1", TEMPLATE}:
        raise ValueError("Unknown dossier template")
    buf = io.BytesIO()
    pdf = Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    pdf.setTitle("CRE property research dossier")
    y = 740

    def line(value, heading=False):
        nonlocal y
        for block in str(value).splitlines() or [""]:
            for part in wrap(block, width=76 if heading else 92) or [""]:
                if y < 56:
                    pdf.showPage()
                    y = 740
                pdf.setFont(
                    "Helvetica-Bold" if heading else "Helvetica", 13 if heading else 10
                )
                pdf.drawString(50, y, part)
                y -= 18 if heading else 14

    line("Property research dossier", True)
    line(f"Property {snapshot['property_id']}")
    line("Source-backed property observations", True)
    if not snapshot["claims"]:
        line("No exportable observations available.")
    for c in snapshot["claims"]:
        line(
            f"{c['predicate']} [{c['verification_state']}]: {json.dumps(c['value'], ensure_ascii=False)}"
        )
        line(
            f"Source {c['dataset_key']} / {c['source_record_id']} / {json.dumps(c['locator'])}; observed {c['observed_at']}"
        )
        if c.get("publisher"):
            line(f"Publisher {c['publisher']} | {c['source_origin']}")
            line(f"Attribution {c['attribution']}")
            line(f"Snapshot {c['run_id']} | SHA-256 {c['content_sha256']}")
    if snapshot["template"] == TEMPLATE:
        render_screening(snapshot["screening"], line)
    if case := snapshot.get("investigation"):
        line("Reviewed ownership investigation", True)
        if "exportable_outcome" in case:
            line(
                f"Outcome from exportable evidence: {case['exportable_outcome'].replace('_', ' ')}"
            )
        if not case["reviewed_findings"]:
            line("No reviewed findings with export permission.")
        for f in case["reviewed_findings"]:
            line(
                f"{f['subject']} - {f['kind']} [{f['state']}]: {f['current_assertion']}"
            )
            line(f"Evidence {f['reference']} / {f['locator']}; review {f['review_id']}")
    if scenario := snapshot.get("scenario"):
        line(f"Modeled scenario: {scenario['name']}", True)
        line(
            f"{scenario['period']} / {scenario['currency']} / {scenario['model_version']}"
        )
        line(
            f"Assumptions: {scenario['assumptions'] or 'No additional assumptions recorded.'}"
        )
        for name, value in sorted(scenario["inputs"].items()):
            if value is not None:
                line(
                    f"{name}: {value} ({scenario['sources'].get(name, 'analyst assumption')})"
                )
        for name, result in sorted(scenario["outputs"].items()):
            if isinstance(result, list):
                for sensitivity in result:
                    line(
                        f"Cap-rate sensitivity {sensitivity['cap_rate']}: {sensitivity['value']} {sensitivity['unit']}"
                    )
            else:
                line(
                    f"{name}: {result['value']} {result['unit']}"
                    if result["value"] is not None
                    else f"{name}: unavailable ({result['reason']})"
                )
    if opportunity := snapshot.get("opportunity"):
        line("Opportunity", True)
        line(
            f"{opportunity['title']} / {opportunity['stage']} / {opportunity['assignee'] or 'unassigned'}"
        )
    line(f"Snapshot SHA-256 {content_digest(snapshot)}")
    pdf.save()
    return buf.getvalue()


def pdf_digest(data):
    return hashlib.sha256(data).hexdigest()
