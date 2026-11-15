import { dealPeriodLabel, type DealFields, type DealProjection } from './deals'

type ControlsProps = {
  fields: DealFields
  termYears: string
  onChange: (field: keyof DealFields, value: string) => void
}

export function DealControls({ fields, termYears, onChange }: ControlsProps) {
  const maxMonths = termYears ? Number(termYears) * 12 : 600
  const feeFields = (comparison: boolean) => {
    const fee = comparison ? 'comparisonFee' : 'primaryFee'
    const treatment = comparison ? 'comparisonFeeTreatment' : 'primaryFeeTreatment'
    return (
      <>
        <label className="field">
          <span>{comparison ? 'Comparison' : 'Primary'} product fee (£)</span>
          <input type="number" min="0" max="9999999999.99" step="0.01"
            value={fields[fee]} onChange={(e) => onChange(fee, e.target.value)} />
        </label>
        <label className="field">
          <span>{comparison ? 'Comparison' : 'Primary'} fee payment</span>
          <select value={fields[treatment]} onChange={(e) => onChange(treatment, e.target.value)}>
            <option value="upfront">Pay upfront from savings</option>
            <option value="financed">Add to the mortgage</option>
          </select>
        </label>
      </>
    )
  }
  return (
    <fieldset className="overpayment-planner deal-controls">
      <legend>New mortgage deal</legend>
      <label className="field">
        <span>New mortgage deal period</span>
        <select value={fields.dealPeriod} onChange={(e) => onChange('dealPeriod', e.target.value)}
          aria-describedby="deal-period-help">
          {[2, 3, 5, 10].map((years) => <option key={years} value={years * 12}>{years}-year fixed</option>)}
          <option value="custom">Other / custom duration</option>
        </select>
      </label>
      <p id="deal-period-help">The deal period is how long the new rate applies. The repayment term is the total time left to pay off the mortgage. Enter the repayment term above to calculate a deal projection.</p>
      {fields.dealPeriod === 'custom' && (
        <label className="field">
          <span>Custom deal period (months)</span>
          <input type="number" min="1" max={maxMonths} step="1" required={!!termYears}
            value={fields.customDealMonths} onChange={(e) => onChange('customDealMonths', e.target.value)} />
        </label>
      )}
      <div className="deal-field-grid">{feeFields(false)}</div>
      <label className="planner-mode">
        <input type="checkbox" checked={fields.compareDeal === 'yes'}
          onChange={(e) => onChange('compareDeal', e.target.checked ? 'yes' : 'no')} />
        Compare a deal with its own rate and fee
      </label>
      {fields.compareDeal === 'yes' && (
        <div className="deal-field-grid">
          <label className="field">
            <span>Comparison deal period (months)</span>
            <input type="number" min="1" max={maxMonths} step="1" required
              value={fields.comparisonMonths} onChange={(e) => onChange('comparisonMonths', e.target.value)} />
            <small>60 months is 5 years.</small>
          </label>
          <label className="field">
            <span>Comparison annual interest rate (%)</span>
            <input type="number" min="0" max="100" step="0.0001" required
              value={fields.comparisonRate} onChange={(e) => onChange('comparisonRate', e.target.value)} />
            <small>Enter the rate you want to test for this deal.</small>
          </label>
          {feeFields(true)}
        </div>
      )}
      <p>These are hypothetical deals. Upfront fees reduce your savings; fees added to the mortgage are repaid with interest.</p>
    </fieldset>
  )
}

type DealRow = { overpayment: number; deal_projections: DealProjection[]; renewal_payments: unknown[] }

export function DealResults({ scenarios, money }: {
  scenarios: DealRow[]
  money: (value: number) => string
}) {
  return (
    <section className="insights-section" aria-labelledby="deal-results-title">
      <div className="insights-heading">
        <h3 id="deal-results-title">What happens when your next mortgage deal ends?</h3>
      </div>
      {!scenarios.some((row) => row.deal_projections.length) && (
        <p>Enter the remaining mortgage repayment term to see end-of-deal estimates.</p>
      )}
      {scenarios.filter((row) => row.deal_projections.length).map((row) => (
        <article className="insight-card" key={row.overpayment}>
          <h4>{row.overpayment ? `${money(row.overpayment)} overpayment` : 'No overpayment'}</h4>
          <div className="deal-results-grid">
            {row.deal_projections.map((deal, index) => (
              <section className="insight-metric deal-result" key={index}>
                <h5>{index < row.renewal_payments.length ? 'Primary' : 'Comparison'} · {dealPeriodLabel(deal.duration_months)} · {deal.annual_interest_rate_percent}%</h5>
                <p>{deal.product_fee ? `${money(deal.product_fee)} fee ${deal.fee_treatment === 'financed' ? 'added to the mortgage' : 'paid upfront'}` : 'No product fee applied'}</p>
                <dl>
                  <div><dt>Starting monthly repayment</dt><dd>{money(deal.estimated_monthly_payment)}</dd></div>
                  <div><dt>Starting balance</dt><dd>{money(deal.balance_at_start)}</dd></div>
                  <div><dt>Ending balance</dt><dd>{money(deal.ending_balance)}</dd></div>
                  <div><dt>Ending equity</dt><dd>{money(deal.ending_equity)}</dd></div>
                  <div><dt>Ending LTV</dt><dd>{deal.ending_ltv_percent.toFixed(2)}%</dd></div>
                  <div><dt>Total mortgage payments</dt><dd>{money(deal.total_payments)}</dd></div>
                  <div><dt>Interest paid</dt><dd>{money(deal.interest_paid)}</dd></div>
                  <div><dt>Principal repaid</dt><dd>{money(deal.principal_repaid)}</dd></div>
                  <div><dt>{deal.cash_after_upfront_fee < 0 ? 'Upfront fee shortfall' : 'Savings after any upfront fee'}</dt><dd>{money(Math.abs(deal.cash_after_upfront_fee))}</dd></div>
                </dl>
              </section>
            ))}
          </div>
        </article>
      ))}
      <p className="insight-disclaimer">Estimates assume an unchanged property value and no extra payments during the new deal. Totals cover each deal’s own duration; they are not a comparison over the same length of time. Mortgage payments exclude upfront fees. Principal on a deal with a financed fee includes repayment of that fee. Early repayment charges and other costs are excluded.</p>
    </section>
  )
}
