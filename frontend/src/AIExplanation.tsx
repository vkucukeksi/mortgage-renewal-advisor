import { useEffect, useRef, useState } from 'react'

export default function AIExplanation({ request }: { request: string }) {
  const [explanation, setExplanation] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])

  async function explain() {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 60000)
    setError('')
    setLoading(true)
    try {
      const response = await fetch('/api/ai/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: request,
        signal: controller.signal,
      })
      const data: unknown = await response.json()
      if (!response.ok) {
        throw new Error(
          typeof data === 'object' && data !== null && 'detail' in data
            && typeof data.detail === 'string'
            ? data.detail : 'AI explanations are unavailable. Please try again.',
        )
      }
      if (typeof data !== 'object' || data === null || !('explanation' in data)
          || typeof data.explanation !== 'string' || !data.explanation.trim()) {
        throw new Error('The AI service returned an unreadable explanation.')
      }
      if (!controller.signal.aborted) setExplanation(data.explanation)
    } catch (err) {
      setError(controller.signal.aborted
        ? 'The explanation request timed out. Please try again.'
        : err instanceof Error ? err.message : 'Could not connect to the AI service.')
    } finally {
      window.clearTimeout(timeout)
      setLoading(false)
    }
  }

  return (
    <section className="assumption-note" aria-labelledby="ai-title" aria-busy={loading}>
      <h3 id="ai-title">Explain with AI</h3>
      <p>
        Get a plain-language explanation of these calculated scenarios.
        Clicking sends your mortgage figures and results to Azure OpenAI.
      </p>
      <button className="primary-button" type="button" onClick={explain} disabled={loading}>
        {loading ? 'Preparing explanation…' : explanation ? 'Explain again' : 'Explain with AI'}
      </button>
      {loading && <p role="status">Generating your explanation…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {explanation && <div className="ai-explanation" aria-live="polite">{explanation}</div>}
      <p>AI-generated explanations may contain mistakes. Check the calculated table.
        For planning only; not financial advice.</p>
    </section>
  )
}
