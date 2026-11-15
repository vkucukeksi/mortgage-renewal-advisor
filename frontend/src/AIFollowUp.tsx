import { useEffect, useRef, useState, type FormEvent } from 'react'
import { askFollowUp, followUpQuestions, maxQuestionLength } from './followUp'

export default function AIFollowUp({ request }: { request: string }) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<Awaited<ReturnType<typeof askFollowUp>> | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const active = useRef<AbortController | null>(null)
  const otherFigures = result?.figures.filter((figure) => figure !== result.explanation) ?? []

  useEffect(() => () => active.current?.abort(), [])

  function updateQuestion(value: string) {
    setQuestion(value)
    setResult(null)
    setError('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setLoading(true)
    setError('')
    setResult(null)
    const timeout = window.setTimeout(() => controller.abort(), 60000)
    try {
      setResult(await askFollowUp(question, request, controller.signal))
    } catch (failure) {
      setError(controller.signal.aborted ? 'The follow-up timed out. Try again.'
        : failure instanceof Error ? failure.message : 'The follow-up failed. Try again.')
    } finally {
      window.clearTimeout(timeout)
      active.current = null
      setLoading(false)
    }
  }

  return (
    <section className="assumption-note follow-up" aria-labelledby="follow-up-title">
      <h3 id="follow-up-title">Ask AI a follow-up</h3>
      <p id="follow-up-help">Ask about a renewal rate, savings to keep or an LTV target.
        Each question uses your current calculator results. Azure OpenAI selects a point to highlight.</p>
      <div className="follow-up-suggestions">
        {followUpQuestions.map((suggestion) => (
          <button type="button" key={suggestion} disabled={loading} onClick={() => updateQuestion(suggestion)}>
            {suggestion}
          </button>
        ))}
      </div>
      <form onSubmit={submit}>
        <label className="field">
          <span>Your question</span>
          <input type="text" value={question} onChange={(e) => updateQuestion(e.target.value)}
            maxLength={maxQuestionLength} aria-describedby="follow-up-help" required disabled={loading} />
        </label>
        <button className="primary-button" type="submit" disabled={loading || !question.trim()}>
          {loading ? 'Checking your scenario…' : 'Ask AI'}
        </button>
      </form>
      {loading && <p role="status">Calculating your follow-up scenario…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {result && (
        <div className="follow-up-result" aria-live="polite">
          <p>{result.answer}</p>
          {result.explanation
            ? <p><b>AI highlight:</b> {result.explanation}</p>
            : <p>AI is unavailable. The calculated answer is still available below.</p>}
          {otherFigures.length > 0 && <ul>{otherFigures.map((figure) => (
            <li key={figure}>{figure}</li>
          ))}</ul>}
          <h4>Assumptions used</h4>
          <ul>{result.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
        </div>
      )}
    </section>
  )
}
