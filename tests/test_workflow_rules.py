import pytest

from cre.workflows.finance import FinancialInputs, calculate
from cre.workflows.research import outcome_for


@pytest.mark.parametrize(
    "egi,expenses,expected",
    [
        (100, 20, "80.00"),
        (0, 0, "0.00"),
        (0, 10, "-10.00"),
        (10, 10, "0.00"),
        ("1.005", 0, "1.01"),
    ],
)
def test_noi(egi, expenses, expected):
    result = calculate(
        FinancialInputs(effective_gross_income=egi, operating_expenses=expenses)
    )
    assert result["noi"]["value"] == expected


@pytest.mark.parametrize(
    "metric,key,denominator,expected",
    [
        ("cap_rate", "property_value", 1000, "0.080000"),
        ("cap_rate", "property_value", 2000, "0.040000"),
        ("cap_rate", "property_value", 0, None),
        ("cap_rate", "property_value", None, None),
        ("dscr", "annual_debt_service", 20, "4.000000"),
        ("dscr", "annual_debt_service", 40, "2.000000"),
        ("dscr", "annual_debt_service", 0, None),
        ("dscr", "annual_debt_service", None, None),
        ("income_value", "valuation_cap_rate", "0.08", "1000.00"),
        ("income_value", "valuation_cap_rate", "0.04", "2000.00"),
        ("income_value", "valuation_cap_rate", 0, None),
        ("income_value", "valuation_cap_rate", None, None),
        ("price_per_sqft", "area_sqft", 100, "10.00"),
        ("price_per_sqft", "area_sqft", 200, "5.00"),
        ("price_per_sqft", "area_sqft", 0, None),
        ("price_per_sqft", "area_sqft", None, None),
        ("cash_on_cash", "cash_invested", 100, "0.600000"),
        ("cash_on_cash", "cash_invested", 200, "0.300000"),
        ("cash_on_cash", "cash_invested", 0, None),
        ("cash_on_cash", "cash_invested", None, None),
    ],
)
def test_financial_fixtures(metric, key, denominator, expected):
    data = dict(
        effective_gross_income=100,
        operating_expenses=20,
        property_value=1000,
        annual_debt_service=20,
    )
    data[key] = denominator
    item = calculate(FinancialInputs(**data))[metric]
    assert item["value"] == expected
    if expected is None:
        assert item["reason"]


def finding(kind, subject="A", **extra):
    return (
        dict(
            kind=kind,
            subject=subject,
            state="verified",
            relationship=None,
            channel_kind=None,
            **extra,
        )
        if not extra
        else {
            "kind": kind,
            "subject": subject,
            "state": "verified",
            "relationship": None,
            "channel_kind": None,
            **extra,
        }
    )


def test_verified_contact_needs_three_independent_dimensions_on_same_subject():
    identity = finding("entity_identity", id="entity-record")
    role = finding(
        "property_role",
        relationship="asset_manager",
        identity_finding_id="entity-record",
    )
    channel = finding(
        "business_channel",
        channel_kind="business_email",
        identity_finding_id="entity-record",
        channel_value="inquiry@example.org",
    )
    assert outcome_for([identity, role, channel], []) == "verified_business_contact"
    assert (
        outcome_for(
            [identity, role, dict(channel, identity_finding_id="other-entity")], []
        )
        != "verified_business_contact"
    )
    assert (
        outcome_for(
            [identity, dict(role, relationship="registered_agent"), channel], []
        )
        != "verified_business_contact"
    )
    assert (
        outcome_for([identity, role, dict(channel, state="candidate")], [])
        != "verified_business_contact"
    )
    assert outcome_for([], []) == "unresolved"


def test_responses_adapter_only_accepts_quotes_from_authorized_excerpts(monkeypatch):
    from uuid import uuid4

    import httpx

    from cre.workflows.research import extract_candidates

    doc = str(uuid4())
    monkeypatch.setenv("CRE_RESEARCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("CRE_OPENAI_MODEL", "fixture-model")
    monkeypatch.setenv("CRE_RESEARCH_INPUT_USD_PER_MILLION", "1.5")
    monkeypatch.setenv("CRE_RESEARCH_OUTPUT_USD_PER_MILLION", "6")
    quote = "The registry lists Example LLC."

    def respond(self, url, headers, json):
        import json as json_module

        assert url == "https://api.openai.com/v1/responses"
        assert json["store"] is False and json["tools"] == []
        assert headers["Authorization"] == "Bearer test-only"
        item = {
            "document_id": doc,
            "subject": "Example LLC",
            "kind": "entity_identity",
            "assertion": quote,
            "quote": quote,
        }
        payload = json_module.dumps(
            {"findings": [item, {**item, "quote": "fabricated"}]}
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": payload}],
                    }
                ],
                "usage": {
                    "total_tokens": 220,
                    "input_tokens": 200,
                    "output_tokens": 20,
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", respond)
    meter = {}
    findings, used = extract_candidates(
        [{"document_id": doc, "text": quote, "locator": "page:1"}], 4000, uuid4(), meter
    )
    assert used == 220 and len(findings) == 1 and findings[0].quote == quote
    assert meter["estimated_usd"] == "0.00042" and meter["model"] == "fixture-model"


def test_scenario_engine_only_accepts_annual_periods():
    from uuid import uuid4
    from pydantic import ValidationError
    from cre.workflows.contracts import ScenarioIn

    with pytest.raises(ValidationError):
        ScenarioIn(property_id=uuid4(), name="Q1", period="Monthly", inputs={})
    assert ScenarioIn(property_id=uuid4(), name="Annual", inputs={}).period == "Annual"


def test_model_contact_verification_matches_the_complete_cited_route():
    from cre.workflows.research import quoted_channel

    quote = "Contact field-team@example.org or (770) 555-0100."
    assert quoted_channel("field-team@example.org", quote)
    assert quoted_channel("+17705550100", quote)
    assert not quoted_channel("team@example.org", quote)
    assert not quoted_channel("+17705550123", quote)
