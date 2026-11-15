import assert from 'node:assert/strict'
import { test } from 'node:test'
import { askFollowUp, followUpQuestions } from '../src/followUp.ts'

test('sends the selected question and calculator snapshot and preserves figures when AI is unavailable', async (t) => {
  const scenario = { overpayment_options: [0, 5000], remaining_term_years: 20 }
  const result = { answer: 'Calculated answer', figures: ['£500.00 per month'], assumptions: ['20-year term'], explanation: null }
  const signal = new AbortController().signal
  t.mock.method(globalThis, 'fetch', async (url, request) => {
    assert.equal(url, '/api/ai/follow-up')
    assert.equal(request.signal, signal)
    assert.deepEqual(JSON.parse(request.body), { question: followUpQuestions[0], scenario })
    return Response.json(result)
  })
  assert.deepEqual(await askFollowUp(followUpQuestions[0], JSON.stringify(scenario), signal), result)
})

test('shows unsupported questions and provider failures as readable errors', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ detail: 'Enter your remaining term at renewal.' }, { status: 422 }))
  const signal = new AbortController().signal
  await assert.rejects(askFollowUp('renewal rate 5%', '{}', signal), /remaining term/)
  fetch.mock.mockImplementation(async () => new Response(null, { status: 503 }))
  await assert.rejects(askFollowUp('renewal rate 5%', '{}', signal), /temporarily unavailable/)
})

test('rejects invalid input before a request and never displays an unrecognised AI claim', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ answer: 'Calculated answer', figures: ['A calculated fact'], assumptions: ['20-year term'], explanation: 'Invented offer' }))
  const signal = new AbortController().signal
  await assert.rejects(askFollowUp(' '.repeat(241), '{}', signal), /240 characters/)
  assert.equal(fetch.mock.callCount(), 0)
  await assert.rejects(askFollowUp('keep £25', '{}', signal), /unreadable answer/)
})
