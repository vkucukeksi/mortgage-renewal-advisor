export const followUpQuestions = [
  'What if my renewal interest rate increases to 5%?',
  'What if I keep £15,000 in savings?',
  'How much would I need to overpay to reach 60% LTV?',
]

export const maxQuestionLength = 240

export async function askFollowUp(question: string, scenario: string, signal: AbortSignal) {
  question = question.trim()
  if (!question || question.length > maxQuestionLength) {
    throw new Error('Enter a question of up to 240 characters.')
  }
  let response: Response
  try {
    response = await fetch('/api/ai/follow-up', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, scenario: JSON.parse(scenario) }),
      signal,
    })
  } catch {
    throw new Error('Could not connect to the follow-up service. Please try again.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(typeof data?.detail === 'string'
      ? data.detail
      : response.status === 422
        ? 'Check your mortgage figures. Follow-ups support up to 10 overpayment options and LTV targets.'
        : 'Follow-up questions are temporarily unavailable. Your calculator results are still available.')
  }
  if (typeof data?.answer !== 'string' || !Array.isArray(data.figures)
      || !data.figures.every((figure: unknown) => typeof figure === 'string')
      || (data.explanation !== null && !data.figures.includes(data.explanation))) {
    throw new Error('The follow-up service returned an unreadable answer.')
  }
  return data as { answer: string; figures: string[]; explanation: string | null }
}
