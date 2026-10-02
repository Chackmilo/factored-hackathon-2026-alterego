import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  api,
  ApiError,
  describeError,
  type AuditRow,
  type CaseRow,
  type HandoffRow,
  type LockRow,
  type Session,
  type TeamQuestion,
} from './api'

interface Props {
  session: Session
  onLogout: () => void
}

type Tab = 'questions' | 'cases' | 'handoffs' | 'locks' | 'audit'

const TABS: { id: Tab; label: string }[] = [
  { id: 'questions', label: 'Questions' },
  { id: 'cases', label: 'Cases' },
  { id: 'handoffs', label: 'Handoffs' },
  { id: 'locks', label: 'Locks' },
  { id: 'audit', label: 'Audit log' },
]

const FORBIDDEN = 'This view requires the agent role'

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.status === 403) return FORBIDDEN
  return describeError(err)
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
}

function fmtUsd(value: number | null | undefined): string {
  if (value == null) return ''
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

function fmtMoney(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount == null) return ''
  if (!currency) return amount.toFixed(2)
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

/** Shared loading state per tab: data, error, refresh. */
function useResource<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await loader())
    } catch (err) {
      setError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [loader])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { data, error, loading, refresh, setData, setError }
}

function Toolbar({ children, loading, onRefresh }: { children?: ReactNode; loading: boolean; onRefresh: () => void }) {
  return (
    <div className="toolbar">
      <div className="row-actions">{children}</div>
      <button type="button" className="btn" disabled={loading} onClick={onRefresh}>
        {loading ? 'Refreshing...' : 'Refresh'}
      </button>
    </div>
  )
}

function List({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) return <span className="muted">none</span>
  return (
    <ul className="plain-list">
      {items.map((item, i) => <li key={i}>{item}</li>)}
    </ul>
  )
}

function Json({ value }: { value: unknown }) {
  if (value == null) return <span className="muted">none</span>
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

// -------------------------------------------------------------- Questions

function QuestionsTab() {
  const [openOnly, setOpenOnly] = useState(true)
  const loader = useCallback(() => api.consoleQuestions(openOnly ? 'open' : undefined), [openOnly])
  const { data, error, loading, refresh, setData, setError } = useResource<TeamQuestion[]>(loader)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [sending, setSending] = useState<string | null>(null)

  const answer = async (q: TeamQuestion) => {
    const text = (drafts[q.question_id] ?? '').trim()
    if (!text) return
    setSending(q.question_id)
    setError(null)
    try {
      const updated = await api.answerQuestion(q.question_id, text)
      setData((prev) => (prev ? prev.map((row) => (row.question_id === q.question_id ? updated : row)) : prev))
      setDrafts((prev) => ({ ...prev, [q.question_id]: '' }))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSending(null)
    }
  }

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <label className="checkbox">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
      </Toolbar>
      <p className="muted">Questions the build could not answer alone. Pick an option or write the team's decision; it is recorded with your agent id and audited.</p>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">No questions.</p>}
      <div className="stack">
        {data?.map((q) => (
          <details key={q.question_id} className="card" open={q.status === 'open'}>
            <summary>
              <code>{q.question_id}</code> <strong>{q.topic}</strong>
              <span className={`pill ${q.status === 'open' ? 'pill-open' : 'pill-done'}`}>{q.status}</span>
            </summary>
            <p>{q.question}</p>
            {q.context && <div className="field"><strong>Context</strong>{q.context}</div>}
            {q.options.length > 0 && (
              <div className="field">
                <strong>Options</strong>
                <div className="row-actions">
                  {q.options.map((opt) => (
                    <button key={opt} type="button" className="btn btn-small" disabled={q.status !== 'open'}
                      onClick={() => setDrafts((prev) => ({ ...prev, [q.question_id]: opt }))}>
                      {opt}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {q.recommendation && <div className="field"><strong>Recommendation</strong>{q.recommendation}</div>}
            {q.source && <div className="field"><strong>Source</strong>{q.source}</div>}
            {q.status === 'answered' ? (
              <div className="field"><strong>Answer</strong>{q.answer} <span className="muted">({q.answered_by}, {fmtDate(q.answered_at)})</span></div>
            ) : (
              <div className="field">
                <strong>Team decision</strong>
                <textarea rows={2} value={drafts[q.question_id] ?? ''} placeholder="Write the decision or pick an option above"
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [q.question_id]: e.target.value }))} />
                <div className="row-actions">
                  <button type="button" className="btn btn-primary" disabled={sending === q.question_id || !(drafts[q.question_id] ?? '').trim()}
                    onClick={() => answer(q)}>
                    {sending === q.question_id ? 'Saving...' : 'Record answer'}
                  </button>
                </div>
              </div>
            )}
          </details>
        ))}
      </div>
    </>
  )
}

// ------------------------------------------------------------------ Cases

function CasesTab() {
  const [candidatesOnly, setCandidatesOnly] = useState(false)
  const loader = useCallback(() => api.consoleCases(candidatesOnly), [candidatesOnly])
  const { data, error, loading, refresh, setData, setError } = useResource<CaseRow[]>(loader)
  const [deciding, setDeciding] = useState<string | null>(null)

  const decide = async (caseId: string, decision: 'approved' | 'rejected') => {
    setDeciding(caseId)
    setError(null)
    try {
      const updated = await api.creditDecision(caseId, decision)
      setData((prev) => (prev ? prev.map((c) => (c.case_id === caseId ? updated : c)) : prev))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setDeciding(null)
    }
  }

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <label className="checkbox">
          <input type="checkbox" checked={candidatesOnly} onChange={(e) => setCandidatesOnly(e.target.checked)} />
          Credit candidates only
        </label>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">No cases.</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Customer</th>
                <th>Transaction</th>
                <th>Subcategory</th>
                <th>Status</th>
                <th>Claimed</th>
                <th>USD</th>
                <th>Clauses</th>
                <th>Credit candidate</th>
                <th>Decision</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.case_id}>
                  <td><code>{c.case_id}</code></td>
                  <td><code>{c.customer_id}</code></td>
                  <td><code>{c.transaction_id}</code></td>
                  <td>{c.subcategory}</td>
                  <td>{c.status}</td>
                  <td>{fmtMoney(c.claimed_amount, c.currency)}</td>
                  <td>{fmtUsd(c.amount_usd)}</td>
                  <td>{c.cited_clauses.join(', ')}</td>
                  <td>{c.provisional_credit_candidate ? `yes (${fmtUsd(c.provisional_credit_amount_usd)})` : 'no'}</td>
                  <td>
                    {!c.provisional_credit_candidate && <span className="muted">n/a</span>}
                    {c.provisional_credit_candidate && c.credit_decision && <span className={`pill ${c.credit_decision}`}>{c.credit_decision}</span>}
                    {c.provisional_credit_candidate && !c.credit_decision && (
                      <span className="row-actions">
                        <button type="button" className="btn btn-small btn-primary" disabled={deciding !== null} onClick={() => decide(c.case_id, 'approved')}>Approve</button>
                        <button type="button" className="btn btn-small" disabled={deciding !== null} onClick={() => decide(c.case_id, 'rejected')}>Reject</button>
                      </span>
                    )}
                  </td>
                  <td>{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// --------------------------------------------------------------- Handoffs

function sortHandoffs(rows: HandoffRow[]): HandoffRow[] {
  return [...rows].sort((a, b) => {
    if (a.status !== b.status) return a.status === 'open' ? -1 : 1
    return b.created_at.localeCompare(a.created_at)
  })
}

function HandoffsTab() {
  const loader = useCallback(async () => sortHandoffs(await api.consoleHandoffs()), [])
  const { data, error, loading, refresh, setData, setError } = useResource<HandoffRow[]>(loader)
  const [resolving, setResolving] = useState<string | null>(null)

  const resolve = async (handoffId: string) => {
    setResolving(handoffId)
    setError(null)
    try {
      const updated = await api.resolveHandoff(handoffId)
      setData((prev) => (prev ? sortHandoffs(prev.map((h) => (h.handoff_id === handoffId ? updated : h))) : prev))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setResolving(null)
    }
  }

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <span className="muted">Open handoffs first, newest first.</span>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">No handoffs.</p>}
      <div className="stack">
        {data?.map((h) => {
          const p = h.packet ?? {}
          return (
            <details key={h.handoff_id} className="card handoff" open={h.status === 'open'}>
              <summary>
                <span className={`pill ${h.status}`}>{h.status}</span>
                <code>{h.handoff_id}</code>
                <span>{h.escalation_reason}</span>
                <span className="muted">customer <code>{h.customer_id}</code>, {fmtDate(h.created_at)}</span>
              </summary>
              <div className="packet">
                <div className="field"><strong>Customer request</strong><p>{p.customer_request || <span className="muted">none</span>}</p></div>
                <div className="field"><strong>Triggering transaction</strong>
                  {p.triggering_transaction ? (
                    <p>
                      <code>{String(p.triggering_transaction.transaction_id ?? '')}</code>{' '}
                      {String(p.triggering_transaction.process_date ?? '')}{' '}
                      {fmtMoney(p.triggering_transaction.amount ?? null, p.triggering_transaction.currency ?? null)}{' '}
                      {p.triggering_transaction.merchant_name ? String(p.triggering_transaction.merchant_name) : ''}
                    </p>
                  ) : <p className="muted">none</p>}
                </div>
                <div className="field"><strong>Verified facts</strong><List items={p.verified_facts} /></div>
                <div className="field"><strong>Supporting evidence</strong><List items={p.supporting_evidence} /></div>
                <div className="field"><strong>Applicable policy clauses</strong><List items={p.applicable_policy_clauses} /></div>
                <div className="field"><strong>Secondary clauses</strong><List items={p.secondary_clauses} /></div>
                <div className="field"><strong>Unresolved questions for the customer</strong><List items={p.unresolved_questions_for_customer} /></div>
                <div className="field"><strong>Card lock</strong><Json value={p.card_lock} /></div>
                <div className="field"><strong>Provisional credit recommendation</strong><Json value={p.provisional_credit_recommendation} /></div>
                <div className="field"><strong>Risk explanation</strong><Json value={p.risk_explanation} /></div>
                <div className="field"><strong>Case memory</strong><Json value={p.case_memory} /></div>
                <details className="sub">
                  <summary>Raw packet</summary>
                  <Json value={h.packet} />
                </details>
                <div className="row-actions">
                  {h.status === 'open' ? (
                    <button type="button" className="btn btn-primary" disabled={resolving !== null} onClick={() => resolve(h.handoff_id)}>
                      {resolving === h.handoff_id ? 'Resolving...' : 'Resolve'}
                    </button>
                  ) : (
                    <span className="muted">Resolved by {h.resolved_by ?? 'agent'} on {fmtDate(h.resolved_at)}</span>
                  )}
                </div>
              </div>
            </details>
          )
        })}
      </div>
    </>
  )
}

// ------------------------------------------------------------------ Locks

function LocksTab() {
  const loader = useCallback(() => api.consoleLocks(), [])
  const { data, error, loading, refresh } = useResource<LockRow[]>(loader)
  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh} />
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">No card locks.</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lock</th>
                <th>Customer</th>
                <th>Product</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Verified</th>
                <th>Conversation</th>
                <th>Created</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.map((l) => (
                <tr key={l.lock_id}>
                  <td><code>{l.lock_id}</code></td>
                  <td><code>{l.customer_id}</code></td>
                  <td><code>{l.product_id ?? ''}</code></td>
                  <td>{l.reason}</td>
                  <td><span className={`pill ${l.status}`}>{l.status}</span></td>
                  <td>{l.verified ? 'yes' : 'no'}</td>
                  <td><code>{l.conversation_id ?? ''}</code></td>
                  <td>{fmtDate(l.created_at)}</td>
                  <td>{fmtDate(l.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------------ Audit

function AuditTab() {
  const [filter, setFilter] = useState('')
  const [applied, setApplied] = useState('')
  // The API returns oldest first when filtered by conversation; the table always shows newest first.
  const loader = useCallback(
    async () => [...(await api.consoleAudit(applied || undefined))].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [applied],
  )
  const { data, error, loading, refresh } = useResource<AuditRow[]>(loader)

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <form
          className="row-actions"
          onSubmit={(e) => {
            e.preventDefault()
            setApplied(filter.trim())
          }}
        >
          <input type="text" value={filter} placeholder="Conversation id" onChange={(e) => setFilter(e.target.value)} aria-label="Conversation id" />
          <button type="submit" className="btn btn-small">Filter</button>
          {applied && (
            <button type="button" className="btn btn-small btn-ghost" onClick={() => { setFilter(''); setApplied('') }}>Clear</button>
          )}
        </form>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">No audit entries.</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Verified</th>
                <th>Conversation</th>
                <th>Customer</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.audit_id}>
                  <td>{fmtDate(a.created_at)}</td>
                  <td>{a.action}</td>
                  <td>{a.actor}</td>
                  <td>{a.verified ? 'yes' : 'no'}</td>
                  <td><code>{a.conversation_id ?? ''}</code></td>
                  <td><code>{a.customer_id ?? ''}</code></td>
                  <td><code className="details">{JSON.stringify(a.details)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// ---------------------------------------------------------------- Console

export default function Console({ session, onLogout }: Props) {
  const [tab, setTab] = useState<Tab>('cases')

  return (
    <main className="page">
      <header className="page-header row">
        <div>
          <h1>HITL Console</h1>
          <p className="muted">Agent <code>{session.label}</code>. Decisions here are recorded; no money moves.</p>
        </div>
        <div className="row-actions">
          <button type="button" className="btn btn-ghost" onClick={onLogout}>Log out</button>
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? 'active' : ''}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <section className="tab-panel" role="tabpanel">
        {tab === 'questions' && <QuestionsTab />}
        {tab === 'cases' && <CasesTab />}
        {tab === 'handoffs' && <HandoffsTab />}
        {tab === 'locks' && <LocksTab />}
        {tab === 'audit' && <AuditTab />}
      </section>
    </main>
  )
}
