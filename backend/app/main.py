
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt, field_validator
from .ai import AIUnavailable, explain_results
from .calculations.mortgage import calculate_monthly_payment, round_money

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


RenewalRate = Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)]


class RenewalScenarioRequest(BaseModel):
    """Input required to calculate renewal scenarios."""

    mortgage_balance: Decimal = Field(ge=0)
    property_value: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    annual_interest_rate_percent: Decimal = Field(ge=0)
    monthly_payment: Decimal = Field(ge=0)
    months_until_renewal: int = Field(ge=0, le=600)
    overpayment_options: list[Decimal] = Field(min_length=1, max_length=100)
    target_ltv_percentages: list[Decimal] = Field(
        default_factory=lambda: [Decimal("60"), Decimal("55"), Decimal("50")],
        min_length=1,
        max_length=100,
    )
    remaining_term_years: StrictInt | None = Field(default=None, ge=1, le=50)
    renewal_interest_rates_percent: list[RenewalRate] = Field(
        default_factory=lambda: [Decimal("3.5"), Decimal("4.5"), Decimal("5.5")],
        min_length=1,
        max_length=10,
    )

    @field_validator("renewal_interest_rates_percent")
    @classmethod
    def unique_renewal_rates(cls, rates: list[Decimal]) -> list[Decimal]:
        if len(set(rates)) != len(rates):
            raise ValueError("Renewal interest rates must be unique.")
        return rates


class RenewalPaymentResponse(BaseModel):
    annual_interest_rate_percent: Decimal
    estimated_monthly_payment: Decimal
    change_from_current_monthly_payment: Decimal


class RenewalScenarioResponse(BaseModel):
    """Results for one renewal overpayment scenario."""

    overpayment: Decimal
    mortgage_balance_after_overpayment: Decimal
    projected_mortgage_balance: Decimal
    projected_ltv_percent: Decimal
    projected_equity: Decimal
    cash_remaining: Decimal
    renewal_payments: list[RenewalPaymentResponse] = Field(default_factory=list)


class ScenarioInsightResponse(BaseModel):
    """A plain-language finding derived from the scenarios."""

    kind: str
    title: str
    message: str
    target_ltv_percent: Decimal | None = None
    overpayment: Decimal | None = None
    projected_ltv_percent: Decimal | None = None
    cash_remaining: Decimal | None = None
    balance_reduction_vs_baseline: Decimal | None = None


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

        insights = generate_scenario_insights(
            scenarios,
            request.target_ltv_percentages,
        )

        scenario_results = []
        for scenario in scenarios:
            payments = []
            if request.remaining_term_years is not None:
                for rate in request.renewal_interest_rates_percent:
                    payment = calculate_monthly_payment(
                        scenario.projected_mortgage_balance,
                        rate,
                        request.remaining_term_years * 12,
                    )
                    payments.append(RenewalPaymentResponse(
                        annual_interest_rate_percent=rate,
                        estimated_monthly_payment=payment,
                        change_from_current_monthly_payment=round_money(
                            payment - request.monthly_payment
                        ),
                    ))
            scenario_results.append(RenewalScenarioResponse(
                **asdict(scenario), renewal_payments=payments,
            ))

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return RenewalScenarioResultsResponse(
        scenarios=scenario_results,
        insights=[
            ScenarioInsightResponse(**asdict(insight))
            for insight in insights
        ],
    )


class AIExplanationResponse(BaseModel):
    explanation: str


@app.post("/api/ai/explain", response_model=AIExplanationResponse)
def explain_renewal_scenarios(request: RenewalScenarioRequest):
    # Reuse validation and the engine; never accept client-calculated results.
    results = create_renewal_scenarios(request)
    try:
        explanation = explain_results(
            request.model_dump(mode="json"), results.model_dump(mode="json")
        )
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return AIExplanationResponse(explanation=explanation)
