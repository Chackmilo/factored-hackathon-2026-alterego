// Typed client for the dispute-intake API. All URLs are relative (/api/...): the Vite dev
// server proxies them to FastAPI on port 8000 and, in production, FastAPI serves the build itself.

export type AppRole = 'customer' | 'agent'
export type Language = 'es' | 'pt'
export type ConversationState = 'new' | 'awaiting_clarification' | 'awaiting_lock_confirmation' | 'closed' | 'escalated'

export interface Persona {
  customer_id: string
  segment: string
  country: string
  account_age_days: number
  complaints_last_90d: number
}

export interface Session {
  token: string
  app_role: AppRole
  customer_id: string
  segment?: string
  country?: string
}

export interface Conversation {
  conversation_id: string
  customer_id: string
  language: Language
  state: ConversationState
  created_at?: string
  updated_at?: string
  messages?: ConversationMessage[]
}

export interface ConversationMessage {
  role: 'customer' | 'assistant'
  masked_text: string
  created_at: string
}

export interface Candidate {
  transaction_id: string
  process_date: string
  amount: number
  currency: string
  amount_usd: number | null
  merchant_name: string
  transaction_type: string | null
  transaction_status: string | null
}

export interface LockOffer {
  lock_id: string | null
  product_id: string | null
  reason: string | null
  required_authentication: string | null
}

export interface VerifiedAction {
  action: string
  verified?: boolean
  [key: string]: unknown
}

export interface TurnResult {
  conversation_id: string
  state: ConversationState
  language: Language
  reply: string
  policy_outcome: string | null
  escalation_reason: string | null
  clarification_reason: string | null
  cited_clauses: string[]
  secondary_clauses: string[]
  case_id: string | null
  handoff_id: string | null
  lock_offer: LockOffer | null
  lock_status: string | null
  candidates: Candidate[]
  actions: VerifiedAction[]
  signals: Record<string, unknown>
}

export interface CaseRow {
  case_id: string
  conversation_id: string | null
  customer_id: string
  transaction_id: string
  subcategory: string
  status: string
  claimed_amount: number | null
  currency: string | null
  amount_usd: number | null
  cited_clauses: string[]
  provisional_credit_candidate: boolean
  provisional_credit_amount_usd: number
  credit_decision: 'approved' | 'rejected' | null
  created_at: string
}

export interface TriggeringTransaction {
  transaction_id?: string
  process_date?: string
  amount?: number
  currency?: string
  amount_usd?: number | null
  merchant_name?: string
  [key: string]: unknown
}

// The packet is free-form JSON on the server. The fields below are the StructuredHandoffPacket
// contract; a failed-action handoff carries a smaller packet, so everything is optional.
export interface HandoffPacket {
  customer_request?: string
  verified_facts?: string[]
  supporting_evidence?: string[]
  applicable_policy_clauses?: string[]
  secondary_clauses?: string[]
  triggering_transaction?: TriggeringTransaction | null
  provisional_credit_recommendation?: Record<string, unknown> | null
  risk_explanation?: Record<string, unknown> | null
  case_memory?: Record<string, unknown>
  card_lock?: Record<string, unknown> | null
  unresolved_questions_for_customer?: string[]
  [key: string]: unknown
}

export interface HandoffRow {
  handoff_id: string
  conversation_id: string | null
  customer_id: string
  escalation_reason: string
  status: 'open' | 'resolved'
  packet: HandoffPacket
  resolved_by?: string | null
  resolved_at?: string | null
  created_at: string
}

export interface LockRow {
  lock_id: string
  conversation_id: string | null
  customer_id: string
  product_id: string | null
  reason: string
  status: string
  verified: boolean
  created_at: string
  updated_at: string
}

export interface TeamQuestion {
  question_id: string
  topic: string
  question: string
  context: string
  options: string[]
  recommendation: string | null
  source: string | null
  status: 'open' | 'answered'
  answer: string | null
  answered_by: string | null
  answered_at: string | null
  created_at: string
}

export interface AuditRow {
  audit_id: string
  conversation_id: string | null
  customer_id: string | null
  actor: string
  action: string
  details: Record<string, unknown>
  verified: boolean
  created_at: string
}

// ---------------------------------------------------------------- session storage

const SESSION_KEY = 'dispute-intake.session'
let currentSession: Session | null = null
let unauthorizedHandler: (() => void) | null = null

export function loadSession(): Session | null {
  if (currentSession) return currentSession
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    currentSession = raw ? (JSON.parse(raw) as Session) : null
  } catch {
    currentSession = null
  }
  return currentSession
}

export function saveSession(session: Session | null): void {
  currentSession = session
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // Storage may be unavailable (private mode); the in-memory copy still works.
  }
}

/** App registers a callback that sends the user back to Login on any 401. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

// ---------------------------------------------------------------- fetch wrapper

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc, msg, type}]
      return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d))).join('; ')
    }
    if (detail != null) return JSON.stringify(detail)
  }
  return fallback
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (auth) {
    const session = loadSession()
    if (session) headers.Authorization = `Bearer ${session.token}`
  }
  let response: Response
  try {
    response = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } })
  } catch {
    throw new ApiError(0, 'Network error: is the API running on port 8000?')
  }
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!response.ok) {
    if (response.status === 401 && auth) {
      saveSession(null)
      unauthorizedHandler?.()
    }
    throw new ApiError(response.status, extractDetail(body, `${response.status} ${response.statusText}`))
  }
  return body as T
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

// ---------------------------------------------------------------- endpoints

export const api = {
  personas: () => request<Persona[]>('/api/v1/auth/personas', {}, false),

  testSession: (customer_id: string, app_role: AppRole) =>
    request<Session>('/api/v1/auth/test-session', { method: 'POST', body: JSON.stringify({ customer_id, app_role }) }, false),

  startConversation: (language: Language) =>
    request<Conversation>('/api/v1/disputes/conversations', { method: 'POST', body: JSON.stringify({ language }) }),

  getConversation: (conversationId: string) =>
    request<Conversation>(`/api/v1/disputes/conversations/${encodeURIComponent(conversationId)}`),

  sendMessage: (conversationId: string, text: string) =>
    request<TurnResult>(`/api/v1/disputes/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  consoleCases: (creditCandidates: boolean) =>
    request<CaseRow[]>(`/api/v1/console/cases${query({ credit_candidates: creditCandidates })}`),

  creditDecision: (caseId: string, decision: 'approved' | 'rejected') =>
    request<CaseRow>(`/api/v1/console/cases/${encodeURIComponent(caseId)}/credit-decision`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),

  consoleHandoffs: (status?: 'open' | 'resolved') =>
    request<HandoffRow[]>(`/api/v1/console/handoffs${query({ status_filter: status })}`),

  resolveHandoff: (handoffId: string) =>
    request<HandoffRow>(`/api/v1/console/handoffs/${encodeURIComponent(handoffId)}/resolve`, { method: 'POST' }),

  consoleLocks: () => request<LockRow[]>('/api/v1/console/locks'),

  consoleQuestions: (status?: 'open' | 'answered') =>
    request<TeamQuestion[]>(`/api/v1/console/questions${query({ status_filter: status })}`),

  answerQuestion: (questionId: string, answer: string) =>
    request<TeamQuestion>(`/api/v1/console/questions/${encodeURIComponent(questionId)}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answer }),
    }),

  fileQuestion: (payload: { topic: string; question: string; context?: string; options?: string[]; recommendation?: string; source?: string }) =>
    request<TeamQuestion>('/api/v1/console/questions', { method: 'POST', body: JSON.stringify(payload) }),

  consoleAudit: (conversationId?: string, limit = 200) =>
    request<AuditRow[]>(`/api/v1/console/audit${query({ conversation_id: conversationId, limit })}`),
}

/** Human-readable message for the red banner. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return String(err)
}
