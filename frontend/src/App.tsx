
import { useState, type FormEvent } from 'react'
import './App.css'

type Scenario = {
  overpayment: number
  mortgage_balance_after_overpayment: number
  projected_mortgage_balance: number
  projected_ltv_percent: number
  projected_equity: number
  cash_remaining: number
}

type ApiScenario = {
  overpayment: number | string
  mortgage_balance_after_overpayment: number | string
  projected_mortgage_balance: number | string
  projected_ltv_percent: number | string
  projected_equity: number | string
  cash_remaining: number | string
}

type ScenarioInsight = {
  kind: string
  title: string
  message: string
  target_ltv_percent: number
  overpayment?: number
  projected_ltv_percent?: number
  cash_remaining?: number
  balance_reduction_vs_no_overpayment?: number
}

type ApiScenarioInsight = {
  kind: string
  title: string
  message: string
  target_ltv_percent: number | string
  overpayment?: number | string | null
  projected_ltv_percent?: number | string | null
  cash_remaining?: number | string | null
  balance_reduction_vs_no_overpayment?: number | string | null
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
  interestRate: '1.89',
  monthlyPayment: '1800',
  monthsUntilRenewal: '6',
  overpaymentOptions: '0, 10000, 20000, 25000, 30000, 50000',
}

const formatMoney = (amount: number) =>
  amount.toLocaleString('en-GB', {
    style: 'currency',
    currency: 'GBP',
    maximumFractionDigits: 0,
  })

function normalizeScenario(scenario: ApiScenario): Scenario {
  const normalized: Scenario = {
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
    Object.values(normalized).some(
      (value) => !Number.isFinite(value),
    )
  ) {
    throw new Error('The API returned invalid scenario values.')
  }

  return normalized
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
    balance_reduction_vs_no_overpayment: optionalNumber(
      insight.balance_reduction_vs_no_overpayment,
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

  function updateField(
    field: keyof typeof initialForm,
    value: string,
  ) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const overpaymentOptions = form.overpaymentOptions
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map(Number)

      if (
        overpaymentOptions.length === 0 ||
        overpaymentOptions.some(
          (value) => !Number.isFinite(value) || value < 0,
        )
      ) {
        throw new Error(
          'Enter valid, non-negative overpayment amounts separated by commas.',
        )
      }

      const requestBody = {
        mortgage_balance: Number(form.mortgageBalance),
        property_value: Number(form.propertyValue),
        available_cash: Number(form.availableCash),
        annual_interest_rate_percent: Number(form.interestRate),
        monthly_payment: Number(form.monthlyPayment),
        months_until_renewal: Number(form.monthsUntilRenewal),
        overpayment_options: overpaymentOptions,
      }

      let response: Response

      try {
        response = await fetch(
          'http://127.0.0.1:8000/api/scenarios',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
          },
        )
      } catch {
        throw new Error(
          'Could not connect to the API. Check that FastAPI is running on port 8000.',
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

      setScenarios(normalizedScenarios)
      setInsights(normalizedInsights)
      setHasCalculated(true)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Something went wrong. Please try again.',
      )
      setScenarios([])
      setInsights([])
      setHasCalculated(false)
    } finally {
      setLoading(false)
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
        <span className="topbar-note">
          Mortgage planning workspace
        </span>
      </header>

      <main className="page-content">
        <section className="page-heading">
          <p className="eyebrow">PLAN WITH CLARITY</p>
          <h1>Make your next mortgage move with confidence.</h1>
          <p className="page-intro">
            Explore how different overpayments could affect your mortgage
            balance, loan-to-value ratio and remaining savings at renewal.
          </p>
        </section>

        <div className="workspace">
          <section className="panel input-panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">STEP 1</p>
                <h2>Your mortgage details</h2>
              </div>
              <span className="heading-icon" aria-hidden="true">↗</span>
            </div>

            <p className="panel-description">
              Example values are prefilled. Replace them with your own
              figures to explore different possibilities.
            </p>

            <form onSubmit={handleSubmit}>
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
                  <span>Monthly payment (£)</span>
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
                <span>Overpayment amounts (£)</span>
                <input
                  type="text"
                  required
                  value={form.overpaymentOptions}
                  onChange={(e) =>
                    updateField('overpaymentOptions', e.target.value)
                  }
                  placeholder="0, 10000, 20000, 25000"
                />
                <small>
                  Enter amounts separated by commas. Each amount must
                  be within your available savings and mortgage balance.
                </small>
              </label>

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
                Your figures are sent to the local development API for
                this calculation. This version does not save mortgage cases.
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

            {!hasCalculated && !loading && (
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

            {loading && (
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

                          {insight.balance_reduction_vs_no_overpayment !== undefined && (
                            <div className="insight-metric">
                              <span>Lower projected balance</span>
                              <strong>
                                {formatMoney(
                                  insight.balance_reduction_vs_no_overpayment,
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
                  monthly payment remain unchanged until renewal.
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
                            {formatMoney(scenario.overpayment)}
                            {scenario.overpayment === 0 && (
                              <span className="scenario-tag">
                                No overpayment
                              </span>
                            )}
                          </td>
                          <td className="balance-cell">
                            {formatMoney(scenario.projected_mortgage_balance)}
                          </td>
                          <td>
                            <span className="ltv-value">
                              {scenario.projected_ltv_percent.toFixed(2)}%
                            </span>
                          </td>
                          <td>{formatMoney(scenario.cash_remaining)}</td>
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
