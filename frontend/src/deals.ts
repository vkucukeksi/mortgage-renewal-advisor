export const dealFields = {
  dealPeriod: '24',
  customDealMonths: '',
  primaryFee: '0',
  primaryFeeTreatment: 'upfront',
  compareDeal: 'no',
  comparisonMonths: '60',
  comparisonRate: '',
  comparisonFee: '0',
  comparisonFeeTreatment: 'upfront',
}

export type DealFields = typeof dealFields

const metricKeys = [
  'duration_months', 'annual_interest_rate_percent', 'product_fee', 'estimated_monthly_payment',
  'balance_at_start', 'ending_balance', 'ending_equity', 'ending_ltv_percent',
  'total_payments', 'interest_paid', 'principal_repaid', 'cash_after_upfront_fee',
] as const
type Metric = typeof metricKeys[number]
export type DealProjection = Record<Metric, number> & { fee_treatment: 'upfront' | 'financed' }
export type ApiDeal = Record<Metric, number | string> & Pick<DealProjection, 'fee_treatment'>

export function normalizeDeal(deal: ApiDeal): DealProjection {
  const metrics = Object.fromEntries(metricKeys.map((key) => [key, Number(deal[key])])) as Record<Metric, number>
  if (Object.values(metrics).some((value) => !Number.isFinite(value)) ||
      !['upfront', 'financed'].includes(deal.fee_treatment)) {
    throw new Error('The API returned invalid deal projection values.')
  }
  return { ...metrics, fee_treatment: deal.fee_treatment }
}

export function dealInputs(fields: DealFields, termYears: number | null) {
  if (!termYears) {
    if (fields.compareDeal === 'yes' || Number(fields.primaryFee) > 0) {
      throw new Error('Enter the remaining mortgage repayment term to apply a product fee or compare deals.')
    }
    return {}
  }
  const termMonths = termYears * 12
  function duration(raw: string) {
    const months = Number(raw)
    if (!Number.isInteger(months) || months < 1 || months > termMonths) {
      throw new Error('Each new deal period must be at least 1 month and no longer than the remaining repayment term.')
    }
    return months
  }
  const fee = (raw: string, treatment: string) => ({
    product_fee: Number(raw || '0'),
    fee_treatment: treatment,
  })
  const period = duration(fields.dealPeriod === 'custom' ? fields.customDealMonths : fields.dealPeriod)
  const comparisonRate = Number(fields.comparisonRate)
  if (fields.compareDeal === 'yes' && (!fields.comparisonRate.trim() || !Number.isFinite(comparisonRate) ||
      comparisonRate < 0 || comparisonRate > 100)) {
    throw new Error('Enter a separate interest rate for the comparison deal.')
  }
  return {
    deal_duration_months: period,
    primary_deal_fee: fee(fields.primaryFee, fields.primaryFeeTreatment),
    comparison_deals: fields.compareDeal === 'yes' ? [{
      duration_months: duration(fields.comparisonMonths),
      annual_interest_rate_percent: comparisonRate,
      ...fee(fields.comparisonFee, fields.comparisonFeeTreatment),
    }] : [],
  }
}

export function dealPeriodLabel(months: number) {
  if (months % 12 === 0) return `${months / 12} ${months === 12 ? 'year' : 'years'}`
  return `${months} ${months === 1 ? 'month' : 'months'}`
}
