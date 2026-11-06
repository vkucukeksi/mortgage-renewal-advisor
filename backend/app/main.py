
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from .ai import AIUnavailable, explain_results
from .ai_guard import GuardUnavailable, Throttled, get_guard, visitor_key
from .body_limit import AIBodyLimit

from .scenarios.insights import generate_scenario_insights
from .scenarios.overpayments import (
    generate_renewal_overpayment_scenarios,
)


app = FastAPI(title="Mortgage Renewal Advisor")
app.add_middleware(AIBodyLimit)


@app.exception_handler(GuardUnavailable)
async def quota_unavailable(_request, _exc):
    return JSONResponse(
        {"detail": "AI safeguards are temporarily unavailable. Mortgage calculations are still available."},
        status_code=503, headers={"Retry-After": "30", "Cache-Control": "no-store"},
    )


@app.exception_handler(Throttled)
async def ai_throttled(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=429,
                        headers={"Retry-After": str(exc.retry_after), "Cache-Control": "no-store"})

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
    months_until_renewal: int = Field(ge=0, le=600)
    overpayment_options: list[Decimal] = Field(min_length=1, max_length=100)
    target_ltv_percentages: list[Decimal] = Field(
        default_factory=lambda: [Decimal("60"), Decimal("55"), Decimal("50")],
        min_length=1,
        max_length=100,
    )


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


class AIExplanationResponse(BaseModel):
    explanation: str


Money = Annotated[Decimal, Field(ge=0, le=Decimal("1000000000000"), max_digits=15, decimal_places=2)]


class AIExplanationRequest(RenewalScenarioRequest):
    # Restrict the paid endpoint without reducing calculator functionality.
    model_config = ConfigDict(extra="forbid")
    mortgage_balance: Money
    property_value: Money = Field(gt=0)
    available_cash: Money
    monthly_payment: Money
    annual_interest_rate_percent: Decimal = Field(ge=0, le=25, max_digits=6, decimal_places=4)
    overpayment_options: list[Money] = Field(min_length=1, max_length=10)
    target_ltv_percentages: list[Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]] = Field(
        default_factory=lambda: [Decimal("60"), Decimal("55"), Decimal("50")],
        min_length=1, max_length=5,
    )


@app.post("/api/ai/explain", response_model=AIExplanationResponse)
def explain_renewal_scenarios(request: AIExplanationRequest, http_request: Request):
    # Reuse validation and the engine; never accept client-calculated results.
    results = create_renewal_scenarios(request)
    try:
        guard = get_guard()
        with guard.admission(visitor_key(http_request)):
            explanation = explain_results(
                request.model_dump(mode="json"), results.model_dump(mode="json")
            )
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return AIExplanationResponse(explanation=explanation)
