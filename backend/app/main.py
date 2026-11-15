
from dataclasses import asdict
from decimal import Decimal
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt, field_validator
from .ai import AIUnavailable, choose_follow_up_point, explain_results
from .calculations.mortgage import calculate_monthly_payment, round_money

from .scenarios.insights import generate_scenario_insights
from .scenarios.follow_up import minimum_overpayment, parse_question
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


FollowUpMoney = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
follow_up_slot = BoundedSemaphore(1)


class FollowUpScenarioRequest(RenewalScenarioRequest):
    mortgage_balance: FollowUpMoney
    property_value: FollowUpMoney = Field(gt=0)
    available_cash: FollowUpMoney
    monthly_payment: FollowUpMoney
    annual_interest_rate_percent: RenewalRate
    overpayment_options: list[FollowUpMoney] = Field(min_length=1, max_length=10)
    target_ltv_percentages: list[RenewalRate] = Field(
        default_factory=lambda: [Decimal("60"), Decimal("55"), Decimal("50")],
        min_length=1, max_length=10,
    )


class FollowUpRequest(BaseModel):
    question: str = Field(min_length=1, max_length=240)
    scenario: FollowUpScenarioRequest


class FollowUpResponse(BaseModel):
    answer: str
    figures: list[str]
    assumptions: list[str]
    explanation: str | None = None


def _follow_up_calculation(question: str, scenario: FollowUpScenarioRequest) -> FollowUpResponse:
    kind, value = parse_question(question)
    # Check the submitted scenario before applying any overrides.
    create_renewal_scenarios(scenario)
    def money(amount: Decimal) -> str:
        return f"£{amount:,.2f}"
    budget = min(scenario.available_cash, scenario.mortgage_balance)
    if kind == "rate":
        if scenario.remaining_term_years is None:
            raise ValueError("Enter your remaining term at renewal and recalculate before asking about a renewal rate.")
        scenario = scenario.model_copy(update={"renewal_interest_rates_percent": [value]})
        answer = f"Estimated monthly repayments at a {value:f}% renewal rate."
    elif kind == "savings":
        if value > scenario.available_cash:
            raise ValueError("The savings you want to keep exceed the available savings in your calculation.")
        limit = min(budget, scenario.available_cash - value)
        scenario = scenario.model_copy(update={"overpayment_options": sorted({Decimal(0), limit})})
        answer = f"You could overpay up to {money(limit)} while keeping at least {money(value)} in savings."
    else:
        required = minimum_overpayment(
            scenario.mortgage_balance, scenario.property_value,
            scenario.annual_interest_rate_percent, scenario.monthly_payment,
            scenario.months_until_renewal, value,
        )
        scenario = scenario.model_copy(update={
            "target_ltv_percentages": [value],
            "overpayment_options": sorted({Decimal(0), min(required, budget)}),
        })
        if required > budget:
            answer = (f"Reaching {value:f}% LTV at renewal would require an overpayment of "
                      f"{money(required)}, which is {money(required - budget)} above your available budget.")
        elif required == 0:
            answer = f"Your projected balance already meets the {value:f}% LTV target without an overpayment."
        else:
            answer = f"The smallest overpayment projected to reach {value:f}% LTV at renewal is {money(required)}."

    results = create_renewal_scenarios(scenario)
    figures = []
    for row in results.scenarios:
        if kind == "rate":
            payment = row.renewal_payments[0]
            figures.append(f"With a {money(row.overpayment)} overpayment, your estimated monthly "
                           f"repayment is {money(payment.estimated_monthly_payment)}.")
        else:
            figures.append(f"With a {money(row.overpayment)} overpayment, your projected renewal balance "
                           f"is {money(row.projected_mortgage_balance)} at {row.projected_ltv_percent:f}% LTV, "
                           f"with {money(row.cash_remaining)} in savings.")
    assumptions = [
        f"Starting mortgage balance {money(scenario.mortgage_balance)}, property value "
        f"{money(scenario.property_value)}, and available savings {money(scenario.available_cash)}.",
        f"Overpayments are made now. The current rate of {scenario.annual_interest_rate_percent:f}% "
        f"and monthly payment of {money(scenario.monthly_payment)} apply for the "
        f"{scenario.months_until_renewal} months until renewal.",
        "Property value stays constant. Estimates exclude fees, early repayment charges and savings interest.",
    ]
    if kind == "rate":
        assumptions.append(
            f"Repayments use a constant {value:f}% renewal rate and a "
            f"{scenario.remaining_term_years}-year remaining term on a standard repayment mortgage."
        )
    return FollowUpResponse(answer=answer, figures=figures, assumptions=assumptions)


@app.post("/api/ai/follow-up", response_model=FollowUpResponse)
def explain_follow_up(request: FollowUpRequest):
    try:
        result = _follow_up_calculation(request.question, request.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    if not follow_up_slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A follow-up is already being explained. Try again shortly.",
                            headers={"Retry-After": "2"})
    try:
        result.explanation = result.figures[choose_follow_up_point(result.figures)]
    except AIUnavailable:
        # Keep the authoritative answer available when the model is offline.
        pass
    finally:
        follow_up_slot.release()
    return result
