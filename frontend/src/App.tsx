
import { useEffect, useRef, useState, type FormEvent } from 'react'
import AIExplanation from './AIExplanation'
import './App.css'

type RenewalPayment = {
  annual_interest_rate_percent: number
  estimated_monthly_payment: number
  change_from_current_monthly_payment: number
}

type Scenario = {
  overpayment: number
  mortgage_balance_after_overpayment: number
  projected_mortgage_balance: number
  projected_ltv_percent: number
  projected_equity: number
  cash_remaining: number
  renewal_payments: RenewalPayment[]
}

type ApiScenario = {
  overpayment: number | string
  mortgage_balance_after_overpayment: number | string
  projected_mortgage_balance: number | string
  projected_ltv_percent: number | string
  projected_equity: number | string
  cash_remaining: number | string
  renewal_payments?: Array<{
    [Field in keyof RenewalPayment]: number | string
  }>
}

type ScenarioInsight = {
  kind: string
  title: string
  message: string
  target_ltv_percent: number
  overpayment?: number
  projected_ltv_percent?: number
  cash_remaining?: number
  balance_reduction_vs_baseline?: number
}

type ApiScenarioInsight = {
  kind: string
  title: string
  message: string
  target_ltv_percent: number | string
  overpayment?: number | string | null
  projected_ltv_percent?: number | string | null
  cash_remaining?: number | string | null
  balance_reduction_vs_baseline?: number | string | null
}

type ApiResponse = {
  scenarios: ApiScenario[]
  insights: ApiScenarioInsight[]
}

type ApiErrorResponse = {
  detail?: string | Array<{ msg?: string }>
}

const initialForm = {
  mortgageBalance: '325000',
  propertyValue: '500000',
  availableCash: '50000',
  interestRate: '2',
  monthlyPayment: '1750',
  monthsUntilRenewal: '6',
  remainingTermYears: '',
  renewalInterestRates: '3.5, 4.5, 5.5',
  overpaymentAmount: '0',
  targetLtvPercentages: '60, 55, 50',
  overpaymentOptions: '0, 10000, 20000, 25000, 30000, 50000',
}

const formatMoney = (amount: number, fractionDigits = 0) =>
  amount.toLocaleString('en-GB', {
    style: 'currency',
    currency: 'GBP',
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })

function normalizeScenario(scenario: ApiScenario): Scenario {
  const figures = {
    overpayment: Number(scenario.overpayment),
    mortgage_balance_after_overpayment: Number(
      scenario.mortgage_balance_after_overpayment,
    ),
    projected_mortgage_balance: Number(
      scenario.projected_mortgage_balance,
    ),
    projected_ltv_percent: Number(scenario.projected_ltv_percent),
    projected_equity: Number(scenario.projected_equity),
    cash_remaining: Number(scenario.cash_remaining),
  }

  if (
    Object.values(figures).some(
      (value) => !Number.isFinite(value),
    )
  ) {
    throw new Error('The API returned invalid scenario values.')
  }

  const renewal_payments = (scenario.renewal_payments ?? []).map((payment) => {
    const normalized = {
      annual_interest_rate_percent: Number(payment.annual_interest_rate_percent),
      estimated_monthly_payment: Number(payment.estimated_monthly_payment),
      change_from_current_monthly_payment: Number(payment.change_from_current_monthly_payment),
    }
    if (Object.values(normalized).some((value) => !Number.isFinite(value))) {
      throw new Error('The API returned invalid renewal payment values.')
    }
    return normalized
  })

  return { ...figures, renewal_payments }
}

function paymentChange(change: number) {
  if (change === 0) return 'Same as your current payment'
  return `${formatMoney(Math.abs(change), 2)} ${change > 0 ? 'higher' : 'lower'} per month`
}

function optionalNumber(
  value: number | string | null | undefined,
): number | undefined {
  if (value === null || value === undefined) {
    return undefined
  }

  const result = Number(value)

  if (!Number.isFinite(result)) {
    throw new Error('The API returned an invalid insight value.')
  }

  return result
}

function normalizeInsight(
  insight: ApiScenarioInsight,
): ScenarioInsight {
  const targetLtv = Number(insight.target_ltv_percent)

  if (!Number.isFinite(targetLtv)) {
    throw new Error('The API returned an invalid insight target.')
  }

  return {
    kind: insight.kind,
    title: insight.title,
    message: insight.message,
    target_ltv_percent: targetLtv,
    overpayment: optionalNumber(insight.overpayment),
    projected_ltv_percent: optionalNumber(
      insight.projected_ltv_percent,
    ),
    cash_remaining: optionalNumber(insight.cash_remaining),
    balance_reduction_vs_baseline: optionalNumber(
      insight.balance_reduction_vs_baseline,
    ),
  }
}

function App() {
  const [form, setForm] = useState(initialForm)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [insights, setInsights] = useState<ScenarioInsight[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hasCalculated, setHasCalculated] = useState(false)
  const [calculatedRequest, setCalculatedRequest] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [plannerPending, setPlannerPending] = useState(false)
  const formElement = useRef<HTMLFormElement>(null)
  const activeRequest = useRef<AbortController | null>(null)
  const debounce = useRef<number | undefined>(undefined)
  const revision = useRef(0)
  const maximumOverpayment = Math.max(0, Math.min(
    Number(form.availableCash) || 0,
    Number(form.mortgageBalance) || 0,
  ))
  const amount = Number(form.overpaymentAmount)
  const validAmount = /^(?:\d+(?:\.\d{0,2})?|\.\d{1,2})$/.test(form.overpaymentAmount)
    && Number.isFinite(amount) && amount <= maximumOverpayment

  useEffect(() => () => {
    window.clearTimeout(debounce.current)
    activeRequest.current?.abort()
  }, [])

  function invalidateResults() {
    window.clearTimeout(debounce.current)
    activeRequest.current?.abort()
    revision.current += 1
    setPlannerPending(false)
    setLoading(false)
    setHasCalculated(false)
    setError('')
  }

  function updateField(
    field: keyof typeof initialForm,
    value: string,
  ) {
    setForm((current) => ({ ...current, [field]: value }))
    invalidateResults()
    if (!advanced && field === 'overpaymentAmount') {
      setPlannerPending(true)
      debounce.current = window.setTimeout(() => {
        setPlannerPending(false)
        const planner = formElement.current
        if (planner?.matches(':valid')) planner.requestSubmit()
      }, 300)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    window.clearTimeout(debounce.current)
    setPlannerPending(false)
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    const submittedRevision = ++revision.current
    setError('')
    setLoading(true)

    try {
      const overpaymentOptions = advanced ? form.overpaymentOptions
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map(Number) : [...new Set([0, amount])]

      if (!advanced && !validAmount) {
        throw new Error('Enter an overpayment within the available limit, using up to two decimal places.')
      }
      if (
        overpaymentOptions.length === 0 ||
        overpaymentOptions.length > 100 ||
        overpaymentOptions.some(
          (value) => !Number.isFinite(value) || value < 0,
        )
      ) {
        throw new Error(
          'Enter 1 to 100 non-negative overpayment amounts separated by commas.',
        )
      }

      if (new Set(overpaymentOptions).size !== overpaymentOptions.length) {
        throw new Error('Each overpayment amount must be unique.')
      }
      if (overpaymentOptions.some((value) => value > maximumOverpayment)) {
        throw new Error('Overpayments cannot exceed your available savings or mortgage balance.')
      }

      const targetLtvPercentages = form.targetLtvPercentages
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map(Number)

      if (
        targetLtvPercentages.length === 0 ||
        targetLtvPercentages.some(
          (value) => !Number.isFinite(value) || value <= 0 || value > 100,
        )
      ) {
        throw new Error(
          'Enter valid LTV targets greater than 0 and at most 100, separated by commas.',
        )
      }

      if (new Set(targetLtvPercentages).size !== targetLtvPercentages.length) {
        throw new Error('Each LTV target must be unique.')
      }

      const renewalInterestRates = form.renewalInterestRates
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map(Number)
      if (
        renewalInterestRates.length === 0 ||
        renewalInterestRates.length > 10 ||
        renewalInterestRates.some((rate) => !Number.isFinite(rate) || rate < 0 || rate > 100) ||
        new Set(renewalInterestRates).size !== renewalInterestRates.length
      ) {
        throw new Error('Enter 1 to 10 distinct renewal rates between 0% and 100%, separated by commas.')
      }

      const requestBody = {
        mortgage_balance: Number(form.mortgageBalance),
        property_value: Number(form.propertyValue),
        available_cash: Number(form.availableCash),
        annual_interest_rate_percent: Number(form.interestRate),
        monthly_payment: Number(form.monthlyPayment),
        months_until_renewal: Number(form.monthsUntilRenewal),
        remaining_term_years: form.remainingTermYears ? Number(form.remainingTermYears) : null,
        renewal_interest_rates_percent: renewalInterestRates,
        target_ltv_percentages: targetLtvPercentages,
        overpayment_options: overpaymentOptions,
      }

      let response: Response

      try {
        response = await fetch(
          '/api/scenarios',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
            signal: controller.signal,
          },
        )
      } catch {
        throw new Error(
          'Could not connect to the calculation service. Please try again.',
        )
      }

      let data: unknown

      try {
        data = await response.json()
      } catch {
        throw new Error('The API returned an unreadable response.')
      }

      if (!response.ok) {
        const errorData = data as ApiErrorResponse
        const detail = errorData.detail

        const message =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((item) => item.msg ?? 'Invalid input').join(' ')
              : 'The API could not calculate these scenarios.'

        throw new Error(message)
      }

      if (
        typeof data !== 'object' ||
        data === null ||
        !('scenarios' in data) ||
        !('insights' in data) ||
        !Array.isArray(data.scenarios) ||
        !Array.isArray(data.insights)
      ) {
        throw new Error('The API returned an unexpected response format.')
      }

      const apiResponse = data as ApiResponse
      const normalizedScenarios =
        apiResponse.scenarios.map(normalizeScenario)
      const normalizedInsights =
        apiResponse.insights.map(normalizeInsight)

      if (submittedRevision !== revision.current) return
      setCalculatedRequest(JSON.stringify(requestBody))
      setScenarios(normalizedScenarios)
      setInsights(normalizedInsights)
      setHasCalculated(true)
    } catch (err) {
      if (submittedRevision !== revision.current) return
      setError(
        err instanceof Error
          ? err.message
          : 'Something went wrong. Please try again.',
      )
      setScenarios([])
      setInsights([])
      setHasCalculated(false)
    } finally {
      if (submittedRevision === revision.current) setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          aria-label="Mortgage Renewal Advisor home"
        >
          <span className="brand-mark">M</span>
          <span>
            Mortgage <strong>Renewal Advisor</strong>
          </span>
        </a>
        <nav aria-label="Main navigation">
          <a className="calculator-link" href="#calculator">Calculator <span aria-hidden="true">↘</span></a>
        </nav>
      </header>

      <main className="page-content">
        <section className="renewal-hero" aria-labelledby="homepage-title">
          <p className="hero-access">Free to explore <span aria-hidden="true">·</span> No sign-up</p>
          <h1 id="homepage-title">Your mortgage deal is ending. <span>What's your next move?</span></h1>
          <p className="page-intro">
            Compare overpayments, projected monthly repayments, loan-to-value (LTV)
            and remaining savings before your mortgage renews.
          </p>
          <a className="hero-action" href="#calculator">
            Explore your mortgage options <span aria-hidden="true">↓</span>
          </a>
          <p className="hero-disclaimer">
            For planning only. Estimates are neither mortgage offers nor regulated financial advice.
          </p>
        </section>

        <ul className="home-highlights" aria-label="What you can explore">
          <li>
            <span className="highlight-mark" aria-hidden="true">£</span>
            <h2>Explore overpayments</h2>
            <p>Adjust an amount to see how it affects your balance, LTV and savings at renewal.</p>
          </li>
          <li>
            <span className="highlight-mark" aria-hidden="true">%</span>
            <h2>Estimate future repayments</h2>
            <p>See what you might pay each month at different renewal rates.</p>
          </li>
          <li>
            <span className="highlight-mark" aria-hidden="true">✦</span>
            <h2>Understand the trade-offs with AI</h2>
            <p>Ask for a plain-language explanation of your calculated scenarios.</p>
          </li>
        </ul>

        <div className="workspace">
          <section className="panel input-panel" id="calculator" aria-labelledby="calculator-title" tabIndex={-1}>
            <div className="panel-heading">
              <div>
                <p className="section-kicker">STEP 1</p>
                <h2 id="calculator-title">Your mortgage details</h2>
              </div>
              <span className="heading-icon" aria-hidden="true">↗</span>
            </div>

            <p className="panel-description">
              Example values are prefilled. Replace them with your own
              figures to explore different possibilities.
            </p>

            <form ref={formElement} onSubmit={handleSubmit}>
              <div className="field-grid">
                <label className="field">
                  <span>Outstanding mortgage (£)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={form.mortgageBalance}
                    onChange={(e) =>
                      updateField('mortgageBalance', e.target.value)
                    }
                  />
                </label>

                <label className="field">
                  <span>Property value (£)</span>
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                    value={form.propertyValue}
                    onChange={(e) =>
                      updateField('propertyValue', e.target.value)
                    }
                  />
                </label>

                <label className="field">
                  <span>Available savings (£)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={form.availableCash}
                    onChange={(e) =>
                      updateField('availableCash', e.target.value)
                    }
                  />
                  <small>
                    Cash you are considering using for an overpayment.
                  </small>
                </label>

                <label className="field">
                  <span>Current interest rate (%)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={form.interestRate}
                    onChange={(e) =>
                      updateField('interestRate', e.target.value)
                    }
                  />
                </label>

                <label className="field">
                  <span>Current monthly payment (£)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={form.monthlyPayment}
                    onChange={(e) =>
                      updateField('monthlyPayment', e.target.value)
                    }
                  />
                </label>

                <label className="field">
                  <span>Months until renewal</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    required
                    value={form.monthsUntilRenewal}
                    onChange={(e) =>
                      updateField('monthsUntilRenewal', e.target.value)
                    }
                  />
                </label>
              </div>

              <label className="field options-field">
                <span>Remaining term at renewal (years)</span>
                <input
                  type="number"
                  min="1"
                  max="50"
                  step="1"
                  value={form.remainingTermYears}
                  onChange={(e) => updateField('remainingTermYears', e.target.value)}
                />
                <small>Enter the whole years left when your current deal ends to compare future payments.</small>
              </label>

              <label className="field options-field">
                <span>Renewal interest rates (%)</span>
                <input
                  type="text"
                  required
                  value={form.renewalInterestRates}
                  onChange={(e) => updateField('renewalInterestRates', e.target.value)}
                />
                <small>Enter up to 10 distinct annual rates separated by commas, using up to four decimal places.</small>
              </label>

              <label className="field options-field">
                <span>LTV milestones (%)</span>
                <input
                  type="text"
                  required
                  value={form.targetLtvPercentages}
                  onChange={(e) =>
                    updateField('targetLtvPercentages', e.target.value)
                  }
                  placeholder="60, 55, 50"
                />
                <small>
                  Choose LTV percentages to analyse, separated by commas.
                  Enter values greater than 0 and up to 100, without duplicates.
                </small>
              </label>

              <fieldset className="overpayment-planner">
                <legend>Overpayment planner</legend>
                <label className="planner-mode">
                  <input type="checkbox" checked={advanced} onChange={(e) => {
                    setAdvanced(e.target.checked)
                    invalidateResults()
                  }} />
                  Advanced: compare multiple amounts
                </label>
                {advanced ? (
                  <label className="field options-field">
                    <span>Overpayment amounts (£)</span>
                    <input
                      type="text"
                      required
                      value={form.overpaymentOptions}
                      onChange={(e) => updateField('overpaymentOptions', e.target.value)}
                    />
                    <small>Separate amounts with commas. Include 0 for a no-overpayment comparison.</small>
                  </label>
                ) : (
                  <>
                    <label className="field options-field">
                      <span>Adjust overpayment</span>
                      <input
                        type="range"
                        min={0}
                        max={maximumOverpayment}
                        step="0.01"
                        disabled={maximumOverpayment === 0}
                        value={Math.min(maximumOverpayment, Math.max(0, amount || 0))}
                        aria-valuetext={formatMoney(Math.min(maximumOverpayment, Math.max(0, amount || 0)), 2)}
                        aria-describedby="overpayment-limit"
                        onChange={(e) => updateField('overpaymentAmount', e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span>Overpayment amount (£)</span>
                      <input
                        type="number"
                        min={0}
                        max={maximumOverpayment}
                        step="0.01"
                        inputMode="decimal"
                        required
                        value={form.overpaymentAmount}
                        aria-invalid={!validAmount}
                        aria-describedby="overpayment-limit"
                        onChange={(e) => updateField('overpaymentAmount', e.target.value)}
                      />
                    </label>
                  </>
                )}
                <p id="overpayment-limit" className="insight-message">
                  Maximum overpayment: {formatMoney(maximumOverpayment, 2)}.
                  {maximumOverpayment === 0 && ' You can still calculate a scenario with no overpayment.'}
                  {!advanced && !validAmount && ' Enter an amount between £0 and the maximum, to the nearest penny.'}
                </p>
              </fieldset>

              {error && (
                <div className="error-message" role="alert">
                  {error}
                </div>
              )}

              <button
                className="primary-button"
                type="submit"
                disabled={loading}
              >
                {loading ? 'Calculating scenarios…' : 'Compare scenarios'}
                {!loading && <span aria-hidden="true"> →</span>}
              </button>

              <p className="form-footnote">
                Your figures are sent to the calculation service.
                This version does not save mortgage cases.
              </p>
            </form>
          </section>

          <section className="panel results-panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">STEP 2</p>
                <h2>Your renewal scenarios</h2>
              </div>
              {hasCalculated && (
                <span className="result-count">
                  {scenarios.length} scenarios
                </span>
              )}
            </div>

            {!hasCalculated && !loading && !plannerPending && (
              <div className="empty-state">
                <div className="empty-illustration" aria-hidden="true">
                  <span>£</span>
                </div>
                <h3>Your options, side by side.</h3>
                <p>
                  Enter your mortgage details and compare how different
                  overpayments could change your position at renewal.
                </p>
                <div className="empty-points">
                  <span><i>✓</i> Projected mortgage balance</span>
                  <span><i>✓</i> Loan-to-value ratio</span>
                  <span><i>✓</i> Equity and cash remaining</span>
                </div>
              </div>
            )}

            {(loading || plannerPending) && (
              <div className="loading-state" role="status">
                Calculating scenarios and insights…
              </div>
            )}

            {hasCalculated && !loading && (
              <>
                {insights.length > 0 && (
                  <section className="insights-section" aria-labelledby="insights-title">
                    <div className="insights-heading">
                      <div>
                        <p className="section-kicker">THE TAKEAWAY</p>
                        <h3 id="insights-title">What stands out</h3>
                      </div>
                      <span className="insight-symbol" aria-hidden="true">
                        ✦
                      </span>
                    </div>

                    {insights.map((insight, index) => (
                      <article
                        className={`insight-card ${insight.kind}`}
                        key={`${insight.kind}-${index}`}
                      >
                        <p className="insight-label">SCENARIO INSIGHT</p>
                        <h4>{insight.title}</h4>
                        <p className="insight-message">
                          {insight.message}
                        </p>

                        <div className="insight-metrics">
                          {insight.overpayment !== undefined && (
                            <div className="insight-metric">
                              <span>Overpayment</span>
                              <strong>{formatMoney(insight.overpayment)}</strong>
                            </div>
                          )}

                          {insight.projected_ltv_percent !== undefined && (
                            <div className="insight-metric">
                              <span>Projected LTV</span>
                              <strong>
                                {insight.projected_ltv_percent.toFixed(2)}%
                              </strong>
                            </div>
                          )}

                          {insight.cash_remaining !== undefined && (
                            <div className="insight-metric">
                              <span>Cash remaining</span>
                              <strong>{formatMoney(insight.cash_remaining)}</strong>
                            </div>
                          )}

                          {insight.balance_reduction_vs_baseline !== undefined && (
                            <div className="insight-metric">
                              <span>Lower projected balance</span>
                              <strong>
                                {formatMoney(
                                  insight.balance_reduction_vs_baseline,
                                )}
                              </strong>
                            </div>
                          )}
                        </div>
                      </article>
                    ))}
                    <p className="insight-disclaimer">
                      Insights compare only the overpayment options you entered.
                      They are scenario findings, not a recommendation to overpay.
                    </p>
                  </section>
                )}

                <div className="results-summary">
                  These projections assume your current interest rate and
                  monthly payment remain unchanged until renewal. Each
                  overpayment is made now, before the first projected month.
                </div>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Overpayment</th>
                        <th>Balance at renewal</th>
                        <th>LTV</th>
                        <th>Cash left</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scenarios.map((scenario, index) => (
                        <tr key={`${scenario.overpayment}-${index}`}>
                          <td className="overpayment-cell">
                            {formatMoney(scenario.overpayment, 2)}
                            {scenario.overpayment === 0 && (
                              <span className="scenario-tag">
                                No overpayment
                              </span>
                            )}
                          </td>
                          <td className="balance-cell">
                            {formatMoney(scenario.projected_mortgage_balance, 2)}
                          </td>
                          <td>
                            <span className="ltv-value">
                              {scenario.projected_ltv_percent.toFixed(2)}%
                            </span>
                          </td>
                          <td>{formatMoney(scenario.cash_remaining, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p className="equity-note">
                  Projected equity ranges from{' '}
                  {formatMoney(
                    Math.min(
                      ...scenarios.map((scenario) => scenario.projected_equity),
                    ),
                  )}{' '}
                  to{' '}
                  {formatMoney(
                    Math.max(
                      ...scenarios.map((scenario) => scenario.projected_equity),
                    ),
                  )}{' '}
                  across these scenarios, assuming the property value stays
                  unchanged.
                </p>
                <section className="insights-section" aria-labelledby="repayment-title">
                  <div className="insights-heading">
                    <h3 id="repayment-title">What could your monthly payment be?</h3>
                  </div>
                  {scenarios[0]?.renewal_payments.length ? (
                    <>
                      <p className="insight-message">
                        Compared with your current payment of <strong>{formatMoney(Number(form.monthlyPayment), 2)}</strong> per month.
                      </p>
                      {scenarios.map((scenario) => (
                        <article className="insight-card" key={scenario.overpayment}>
                          <h4>{scenario.overpayment === 0 ? 'No overpayment' : `${formatMoney(scenario.overpayment, 2)} overpayment`}</h4>
                          <dl className="repayment-grid">
                            {scenario.renewal_payments.map((payment) => (
                              <div className="insight-metric" key={payment.annual_interest_rate_percent}>
                                <dt>{payment.annual_interest_rate_percent}% annual rate</dt>
                                <dd><strong>{formatMoney(payment.estimated_monthly_payment, 2)}</strong> per month</dd>
                                <dd>{paymentChange(payment.change_from_current_monthly_payment)}</dd>
                              </div>
                            ))}
                          </dl>
                        </article>
                      ))}
                      <p className="insight-disclaimer">
                        Estimates use each projected renewal balance, the entered term at renewal
                        and a constant scenario rate. They cover standard repayment mortgages
                        with monthly payments and exclude fees and charges.
                      </p>
                    </>
                  ) : (
                    <p className="insight-message">Enter your remaining term at renewal to see payment estimates.</p>
                  )}
                </section>
                <AIExplanation key={calculatedRequest} request={calculatedRequest} />
              </>
            )}

            <div className="assumption-note">
              <strong>Important assumption</strong>
              <p>
                These are simplified estimates, not lender quotations. Actual
                balances may vary due to payment dates, daily interest,
                overpayment limits and lender rules.
              </p>
            </div>
          </section>
        </div>

        <footer className="page-footer">
          <p>
            For educational and planning purposes only. This tool is not
            financial advice and does not replace regulated mortgage or
            financial advice.
          </p>
          <span>Mortgage Renewal Advisor · Early access</span>
        </footer>
      </main>
    </div>
  )
}

export default App
