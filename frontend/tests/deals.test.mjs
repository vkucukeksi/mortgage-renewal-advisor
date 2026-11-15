import assert from 'node:assert/strict'
import { test } from 'node:test'
import { dealFields, dealInputs, dealPeriodLabel, normalizeDeal } from '../src/deals.ts'

test('defaults to two years and sends independent comparison assumptions', () => {
  assert.equal(dealInputs(dealFields, 20).deal_duration_months, 24)
  const fields = { ...dealFields, compareDeal: 'yes', comparisonRate: '4.125',
    comparisonFee: '999.25', comparisonFeeTreatment: 'financed' }
  assert.deepEqual(dealInputs(fields, 20).comparison_deals, [{
    duration_months: 60, annual_interest_rate_percent: 4.125,
    product_fee: 999.25, fee_treatment: 'financed',
  }])
  assert.throws(() => dealInputs({ ...fields, comparisonRate: '' }, 20), /separate interest rate/)
})

test('validates duration against term and supports custom months', () => {
  const custom = { ...dealFields, dealPeriod: 'custom', customDealMonths: '17' }
  assert.equal(dealInputs(custom, 2).deal_duration_months, 17)
  assert.throws(() => dealInputs(custom, 1), /remaining repayment term/)
  assert.deepEqual(dealInputs(dealFields, null), {})
  assert.equal(dealPeriodLabel(17), '17 months')
  assert.equal(dealPeriodLabel(60), '5 years')
})

test('refuses unreadable projections rather than calculating replacement figures', () => {
  assert.throws(() => normalizeDeal({ ending_balance: '0' }), /invalid deal projection/)
})
