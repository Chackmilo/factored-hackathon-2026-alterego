import { useEffect, useState } from 'react'
import { api, describeError, type Persona, type Session } from './api'

const AGENT_ID = 'AGENT-1'

interface Props {
  onLogin: (session: Session) => void
}

export default function Login({ onLogin }: Props) {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .personas()
      .then((rows) => {
        if (!cancelled) setPersonas(rows)
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const enter = async (customerId: string, role: 'customer' | 'agent') => {
    setBusy(customerId)
    setError(null)
    try {
      onLogin(await api.testSession(customerId, role))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="page page-narrow">
      <header className="page-header">
        <h1>Dispute Intake</h1>
        <p className="muted">Demo login. Pick a test persona or open the HITL console.</p>
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      <section className="card">
        <h2>Customers</h2>
        {loading && <p className="muted">Loading personas...</p>}
        {!loading && personas.length === 0 && !error && <p className="muted">No personas available.</p>}
        <div className="stack">
          {personas.map((p) => (
            <button
              key={p.customer_id}
              className="btn btn-block"
              disabled={busy !== null}
              onClick={() => enter(p.customer_id, 'customer')}
            >
              Enter as customer {p.customer_id} ({p.segment}, {p.country})
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Operations</h2>
        <button className="btn btn-primary btn-block" disabled={busy !== null} onClick={() => enter(AGENT_ID, 'agent')}>
          Enter HITL console as agent
        </button>
      </section>
    </main>
  )
}
