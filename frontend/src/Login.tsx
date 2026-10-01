import { useEffect, useState, type FormEvent } from 'react'
import { api, clearSession, describeError, type AppRole, type Persona, type Session } from './api'
import { supabase } from './supabase'

const AGENT_ID = 'AGENT-1'

interface Props {
  onLogin: (session: Session) => void
}

// With the Supabase keys in the build, people sign in with the email and password they received;
// without them, the local issuer's persona picker (the API answers it in development and test only).
export default function Login({ onLogin }: Props) {
  return supabase ? <PasswordLogin onLogin={onLogin} /> : <PersonaLogin onLogin={onLogin} />
}

function PasswordLogin({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!supabase) return
    setBusy(true)
    setError(null)
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
      if (authError) {
        setError(authError.code === 'invalid_credentials' ? 'Email or password is incorrect.' : authError.message)
        return
      }
      onLogin({ ...(await api.me()), label: email.trim() })
    } catch (err) {
      await clearSession() // signed in to Supabase, but the API refused the account (403) or did not answer
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page page-narrow">
      <header className="page-header">
        <h1>Dispute Intake</h1>
        <p className="muted">Sign in with the account you received.</p>
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      <form className="card stack" onSubmit={submit}>
        <label className="stack">
          Email
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="stack">
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

function PersonaLogin({ onLogin }: Props) {
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

  const enter = async (customerId: string, role: AppRole) => {
    setBusy(customerId)
    setError(null)
    try {
      const local = await api.testSession(customerId, role)
      onLogin({ ...(await api.me(local.token)), label: customerId, token: local.token })
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
