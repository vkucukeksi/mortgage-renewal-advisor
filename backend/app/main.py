
from dataclasses import asdict
from decimal import Decimal
from threading import BoundedSemaphore
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from .ai import AIUnavailable, choose_follow_up_point, explain_results
from .calculations.mortgage import round_money
from .calculations.deals import project_deal

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


DealMonths = Annotated[StrictInt, Field(ge=1, le=600)]


class DealFee(BaseModel):
    product_fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    fee_treatment: Literal["upfront", "financed"] = "upfront"


class ComparisonDeal(DealFee):
    duration_months: DealMonths
    annual_interest_rate_percent: RenewalRate


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

    deal_duration_months: DealMonths | None = None
    primary_deal_fee: DealFee = Field(default_factory=DealFee)
    comparison_deals: list[ComparisonDeal] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_deal_periods(self):
        if self.remaining_term_years is None:
            if self.deal_duration_months is not None or self.comparison_deals or self.primary_deal_fee.product_fee:
                raise ValueError("Enter the remaining mortgage repayment term to project mortgage deals.")
        else:
            term = self.remaining_term_years * 12
            durations = [deal.duration_months for deal in self.comparison_deals]
            if self.deal_duration_months is not None:
                durations.append(self.deal_duration_months)
            if any(duration > term for duration in durations):
                raise ValueError("The new mortgage deal period cannot exceed the remaining repayment term.")
        return self

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


class DealResponse(BaseModel):
    duration_months: int
    annual_interest_rate_percent: Decimal
    product_fee: Decimal
    fee_treatment: Literal["upfront", "financed"]
    estimated_monthly_payment: Decimal
    balance_at_start: Decimal
    ending_balance: Decimal
    ending_equity: Decimal
    ending_ltv_percent: Decimal
    total_payments: Decimal
    interest_paid: Decimal
    principal_repaid: Decimal
    cash_after_upfront_fee: Decimal


class RenewalScenarioResponse(BaseModel):
    """Results for one renewal overpayment scenario."""

    overpayment: Decimal
    mortgage_balance_after_overpayment: Decimal
    projected_mortgage_balance: Decimal
    projected_ltv_percent: Decimal
    projected_equity: Decimal
    cash_remaining: Decimal
    renewal_payments: list[RenewalPaymentResponse] = Field(default_factory=list)
    deal_projections: list[DealResponse] = Field(default_factory=list)


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
            deals = []
            if request.remaining_term_years is not None:
                term = request.remaining_term_years * 12
                period = request.deal_duration_months or min(24, term)
                base_deals = [
                    ComparisonDeal(duration_months=period, annual_interest_rate_percent=rate,
                                   **request.primary_deal_fee.model_dump())
                    for rate in request.renewal_interest_rates_percent
                ]
                for index, deal in enumerate(base_deals + request.comparison_deals):
                    effective_fee = deal.product_fee if scenario.projected_mortgage_balance else Decimal(0)
                    projection = project_deal(
                        scenario.projected_mortgage_balance, request.property_value,
                        scenario.cash_remaining, deal.annual_interest_rate_percent,
                        term, deal.duration_months, effective_fee, deal.fee_treatment == "financed",
                    )
                    deals.append(DealResponse(
                        **deal.model_dump(exclude={"product_fee"}), product_fee=effective_fee,
                        **asdict(projection),
                    ))
                    if index < len(base_deals):
                        payments.append(RenewalPaymentResponse(
                            annual_interest_rate_percent=deal.annual_interest_rate_percent,
                            estimated_monthly_payment=projection.estimated_monthly_payment,
                            change_from_current_monthly_payment=round_money(
                                projection.estimated_monthly_payment - request.monthly_payment
                            ),
                        ))
            scenario_results.append(RenewalScenarioResponse(
                **asdict(scenario), renewal_payments=payments, deal_projections=deals,
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
        if request.deal_duration_months is not None or request.comparison_deals or request.primary_deal_fee.product_fee:
            points = deal_points(results, include_renewal=True)
            if points:
                selected = points[choose_follow_up_point(points[:12])]
                return AIExplanationResponse(explanation=f"{selected}\n\n{DEAL_TRADE_OFFS}")
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


DEAL_TRADE_OFFS = (
    "Shorter fixed periods let you reconsider sooner, but expose you sooner to unknown rates "
    "and possible new product fees. Longer fixes give more payment certainty, but can reduce "
    "flexibility if you move or want to switch early. Compare the fees as well as the rate. "
    "Interest totals cover different lengths of time, so they do not show which deal costs less "
    "over the same horizon. These are hypothetical estimates, not mortgage offers or financial advice."
)


def deal_points(results: RenewalScenarioResultsResponse, include_renewal: bool = False) -> list[str]:
    def money(amount: Decimal) -> str:
        return f"£{amount:,.2f}"

    # Put the first primary and the comparison near the front of the AI input.
    rows = results.scenarios
    if not rows:
        return []
    points = []
    for row in rows:
        order = [0, len(row.deal_projections) - 1, *range(1, len(row.deal_projections) - 1)]
        for i in dict.fromkeys(order):
            if not 0 <= i < len(row.deal_projections):
                continue
            deal = row.deal_projections[i]
            label = "added to the mortgage" if deal.fee_treatment == "financed" else "paid upfront"
            option = "primary" if i < len(row.renewal_payments) else "comparison"
            points.append(
                f"With a {money(row.overpayment)} overpayment, a {deal.duration_months}-month deal ({option}) "
                f"at {deal.annual_interest_rate_percent:f}% with a {money(deal.product_fee)} fee {label} "
                f"starts at {money(deal.estimated_monthly_payment)} per month. It ends with "
                f"{money(deal.ending_balance)} outstanding at {deal.ending_ltv_percent:f}% LTV, after "
                f"{money(deal.interest_paid)} interest and {money(deal.principal_repaid)} principal repaid."
                + (f" Before any product fee, the renewal balance is {money(row.projected_mortgage_balance)} "
                   f"at {row.projected_ltv_percent:f}% LTV, with {money(row.cash_remaining)} in savings."
                   if include_renewal else "")
            )
    return points


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
        if scenario.comparison_deals:
            answer += " The comparison deal keeps its own entered rate."
    elif kind == "deal":
        if scenario.remaining_term_years is None:
            raise ValueError("Enter your remaining term at renewal and recalculate before comparing deals.")
        months = int(value)
        if not 1 <= months <= scenario.remaining_term_years * 12:
            raise ValueError("Enter a positive deal period no longer than the remaining repayment term.")
        scenario = scenario.model_copy(update={"deal_duration_months": months})
        answer = f"End-of-deal projections for a {months}-month primary deal. {DEAL_TRADE_OFFS}"
    elif kind == "savings":
        if value > scenario.available_cash:
            raise ValueError("The savings you want to keep exceed the available savings in your calculation.")
        limit = min(budget, scenario.available_cash - value)
        scenario = scenario.model_copy(update={"overpayment_options": sorted({Decimal(0), limit})})
        answer = f"You could overpay up to {money(limit)} while keeping at least {money(value)} in savings."
        if any(fee.product_fee and fee.fee_treatment == "upfront"
               for fee in [scenario.primary_deal_fee, *scenario.comparison_deals]):
            answer += " This reserve is measured before any upfront product fees."
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
        if kind == "deal":
            continue
        if kind == "rate":
            payment = row.renewal_payments[0]
            figures.append(f"With a {money(row.overpayment)} overpayment, your estimated monthly "
                           f"repayment is {money(payment.estimated_monthly_payment)}.")
        else:
            figures.append(f"With a {money(row.overpayment)} overpayment, your projected renewal balance "
                           f"is {money(row.projected_mortgage_balance)} at {row.projected_ltv_percent:f}% LTV, "
                           f"with {money(row.cash_remaining)} in savings.")
    if kind == "deal" or scenario.deal_duration_months is not None or scenario.comparison_deals or scenario.primary_deal_fee.product_fee:
        figures.extend(deal_points(results))
    assumptions = [
        f"Starting mortgage balance {money(scenario.mortgage_balance)}, property value "
        f"{money(scenario.property_value)}, and available savings {money(scenario.available_cash)}.",
        f"Overpayments are made now. The current rate of {scenario.annual_interest_rate_percent:f}% "
        f"and monthly payment of {money(scenario.monthly_payment)} apply for the "
        f"{scenario.months_until_renewal} months until renewal.",
        "Property value stays constant. Estimates exclude early repayment charges and savings interest.",
    ]
    if kind == "deal" or scenario.deal_duration_months is not None or scenario.comparison_deals or scenario.primary_deal_fee.product_fee:
        assumptions.append(
            f"Deal projections use a {scenario.remaining_term_years}-year repayment term and each deal's "
            "stated fixed rate and product fee. Upfront fees reduce cash; financed fees increase the loan. "
            "No other fees or changes after the fixed period are modelled."
        )
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
        result.explanation = result.figures[choose_follow_up_point(result.figures[:12])]
    except AIUnavailable:
        # Keep the authoritative answer available when the model is offline.
        pass
    finally:
        follow_up_slot.release()
    return result
