"""Annual indicative scenarios. Rates are decimal fractions, money uses half-up rounding."""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Amount = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=6)]
Rate = Annotated[Decimal, Field(ge=0, le=1, max_digits=8, decimal_places=6)]
MODEL_VERSION = "annual-income-v1"


class FinancialInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_gross_income: Amount | None = None
    operating_expenses: Amount | None = None
    property_value: Amount | None = None
    annual_debt_service: Amount | None = None
    area_sqft: Amount | None = None
    cash_invested: Amount | None = None
    valuation_cap_rate: Rate | None = None
    sensitivity_rates: list[Rate] = Field(default_factory=list, max_length=20)


def metric(value, unit, reason=None):
    if value is None:
        return {"value": None, "unit": unit, "reason": reason}
    places = (
        Decimal("0.000001") if unit in {"fraction", "multiple"} else Decimal("0.01")
    )
    return {"value": str(value.quantize(places, rounding=ROUND_HALF_UP)), "unit": unit}


def ratio(numerator, denominator, unit, denominator_name):
    if numerator is None or denominator is None:
        return metric(None, unit, "Required input unavailable")
    if denominator == 0:
        return metric(None, unit, f"{denominator_name} is zero")
    return metric(numerator / denominator, unit)


def calculate(data: FinancialInputs):
    with localcontext() as precision:
        precision.prec = 48
        noi = None
        if (
            data.effective_gross_income is not None
            and data.operating_expenses is not None
        ):
            noi = data.effective_gross_income - data.operating_expenses
        cash = (
            None
            if noi is None or data.annual_debt_service is None
            else noi - data.annual_debt_service
        )
        return {
            "noi": metric(noi, "currency", "Income or operating expenses unavailable"),
            "cap_rate": ratio(noi, data.property_value, "fraction", "Property value"),
            "dscr": ratio(
                noi, data.annual_debt_service, "multiple", "Annual debt service"
            ),
            "income_value": ratio(
                noi, data.valuation_cap_rate, "currency", "Valuation cap rate"
            ),
            "price_per_sqft": ratio(
                data.property_value, data.area_sqft, "currency/sqft", "Area"
            ),
            "cash_on_cash": ratio(
                cash, data.cash_invested, "fraction", "Cash invested"
            ),
            "cap_rate_sensitivity": [
                {"cap_rate": str(rate), **ratio(noi, rate, "currency", "Cap rate")}
                for rate in data.sensitivity_rates
            ],
        }
