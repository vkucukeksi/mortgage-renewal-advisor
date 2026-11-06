import { useEffect, useRef, useState } from 'react'

export default function AIExplanation({ request }: { request: string }) {
  const [explanation, setExplanation] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [retryAt, setRetryAt] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])
  useEffect(() => {
    if (!retryAt) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [retryAt])
  const retrySeconds = Math.max(0, Math.ceil((retryAt - now) / 1000))

  async function explain() {
    if (loading || Date.now() < retryAt) return
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
      if (response.status === 429 || response.status === 503) {
        const header = response.headers.get('Retry-After')
        const seconds = header === null ? (response.status === 429 ? 30 : 0) : Number(header)
        const delay = Number.isFinite(seconds) ? Math.min(86400, Math.max(0, seconds)) : 30
        setNow(Date.now())
        setRetryAt(Date.now() + delay * 1000)
      }
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
      <button className="primary-button" type="button" onClick={explain} disabled={loading || retrySeconds > 0}>
        {loading ? 'Preparing explanation…' : explanation ? 'Explain again' : 'Explain with AI'}
      </button>
      {loading && <p role="status">Generating your explanation…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {retrySeconds > 0 && <p role="status">
        {retrySeconds >= 3600
          ? `Try again after ${new Date(retryAt).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}.`
          : `Try again in ${retrySeconds} seconds.`}
        {' '}Your mortgage calculations are still available.
      </p>}
      {explanation && <div className="ai-explanation" aria-live="polite">{explanation}</div>}
      <p>AI-generated explanations may contain mistakes. Check the calculated table.
        For planning only; not financial advice.</p>
    </section>
  )
}
