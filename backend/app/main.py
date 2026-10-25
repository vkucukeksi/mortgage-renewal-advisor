
from dataclasses import asdict
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .scenarios.insights import generate_scenario_insights
from .scenarios.overpayments import (
    generate_renewal_overpayment_scenarios,
)


app = FastAPI(title="Mortgage Renewal Advisor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RenewalScenarioRequest(BaseModel):
    """Input required to calculate renewal scenarios."""

    mortgage_balance: Decimal = Field(ge=0)
    property_value: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    annual_interest_rate_percent: Decimal = Field(ge=0)
    monthly_payment: Decimal = Field(ge=0)
    months_until_renewal: int = Field(ge=0)
    overpayment_options: list[Decimal] = Field(min_length=1)


class RenewalScenarioResponse(BaseModel):
    """Results for one renewal overpayment scenario."""

    overpayment: Decimal
    mortgage_balance_after_overpayment: Decimal
    projected_mortgage_balance: Decimal
    projected_ltv_percent: Decimal
    projected_equity: Decimal
    cash_remaining: Decimal


class ScenarioInsightResponse(BaseModel):
    """A plain-language finding derived from the scenarios."""

    kind: str
    title: str
    message: str
    target_ltv_percent: Decimal
    overpayment: Decimal | None = None
    projected_ltv_percent: Decimal | None = None
    cash_remaining: Decimal | None = None
    balance_reduction_vs_no_overpayment: Decimal | None = None


class RenewalScenarioResultsResponse(BaseModel):
    """Complete scenario results and their explanatory insights."""

    scenarios: list[RenewalScenarioResponse]
    insights: list[ScenarioInsightResponse]


@app.get("/")
def root():
    return {
        "message": "Mortgage Renewal Advisor API is running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post(
    "/api/scenarios",
    response_model=RenewalScenarioResultsResponse,
)
def create_renewal_scenarios(
    request: RenewalScenarioRequest,
):
    """Generate renewal scenarios and explain LTV milestones."""

    try:
        scenarios = generate_renewal_overpayment_scenarios(
            mortgage_balance=request.mortgage_balance,
            property_value=request.property_value,
            available_cash=request.available_cash,
            annual_interest_rate_percent=(
                request.annual_interest_rate_percent
            ),
            monthly_payment=request.monthly_payment,
            months_until_renewal=request.months_until_renewal,
            overpayment_options=request.overpayment_options,
        )

        insights = generate_scenario_insights(scenarios)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return RenewalScenarioResultsResponse(
        scenarios=[
            RenewalScenarioResponse(**asdict(scenario))
            for scenario in scenarios
        ],
        insights=[
            ScenarioInsightResponse(**asdict(insight))
            for insight in insights
        ],
    )
