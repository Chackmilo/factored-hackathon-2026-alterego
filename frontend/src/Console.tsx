import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  api,
  ApiError,
  describeError,
  type AuditRow,
  type CaseRow,
  type HandoffRow,
  type LockRow,
  type Session,
} from './api'

interface Props {
  session: Session
  onLogout: () => void
}

type Tab = 'cases' | 'handoffs' | 'locks' | 'audit'

const TABS: { id: Tab; label: keyof Labels }[] = [
  { id: 'cases', label: 'tabCases' },
  { id: 'handoffs', label: 'tabHandoffs' },
  { id: 'locks', label: 'tabLocks' },
  { id: 'audit', label: 'tabAudit' },
]

type ConsoleLanguage = 'es' | 'pt' | 'en'

const LANGUAGES: ConsoleLanguage[] = ['es', 'pt', 'en']
const LOCALES: Record<ConsoleLanguage, string> = { es: 'es', pt: 'pt-BR', en: 'en-US' }
const LANGUAGE_KEY = 'console.language'

// Only the console's own text changes language; the data (clauses, reasons, packets) stays as recorded.
const LABELS = {
  es: {
    title: 'Consola HITL',
    agent: 'Agente',
    subtitle: 'Las decisiones de aquí quedan registradas; no se mueve dinero.',
    logout: 'Salir',
    language: 'Idioma',
    tabCases: 'Casos',
    tabHandoffs: 'Escalaciones',
    tabLocks: 'Bloqueos',
    tabAudit: 'Auditoría',
    forbidden: 'Esta vista requiere el rol de agente',
    refresh: 'Actualizar',
    refreshing: 'Actualizando...',
    none: 'ninguno',
    creditOnly: 'Solo candidatos a crédito',
    noCases: 'No hay casos.',
    colCase: 'Caso',
    colCustomer: 'Cliente',
    colTransaction: 'Transacción',
    colSubcategory: 'Subcategoría',
    colStatus: 'Estado',
    colClaimed: 'Reclamado',
    colUsd: 'USD',
    colClauses: 'Cláusulas',
    colCreditCandidate: 'Candidato a crédito',
    colDecision: 'Decisión',
    colCreated: 'Creado',
    yes: 'sí',
    no: 'no',
    notApplicable: 'n/a',
    approve: 'Aprobar',
    reject: 'Rechazar',
    handoffsOrder: 'Abiertas primero, las más recientes primero.',
    noHandoffs: 'No hay escalaciones.',
    customer: 'cliente',
    customerRequest: 'Solicitud del cliente',
    triggeringTransaction: 'Transacción que la origina',
    verifiedFacts: 'Hechos verificados',
    supportingEvidence: 'Evidencia de soporte',
    applicableClauses: 'Cláusulas de política aplicables',
    secondaryClauses: 'Cláusulas secundarias',
    unresolvedQuestions: 'Preguntas pendientes para el cliente',
    cardLock: 'Bloqueo de tarjeta',
    creditRecommendation: 'Recomendación de crédito provisional',
    riskExplanation: 'Explicación del riesgo',
    caseMemory: 'Memoria del caso',
    rawPacket: 'Paquete completo',
    resolving: 'Resolviendo...',
    resolve: 'Resolver',
    resolvedBy: 'Resuelta por',
    on: 'el',
    noLocks: 'No hay bloqueos de tarjeta.',
    colLock: 'Bloqueo',
    colProduct: 'Producto',
    colReason: 'Motivo',
    colVerified: 'Verificado',
    colConversation: 'Conversación',
    colUpdated: 'Actualizado',
    conversationId: 'Id de conversación',
    filter: 'Filtrar',
    clear: 'Limpiar',
    noAudit: 'No hay registros de auditoría.',
    colWhen: 'Cuándo',
    colAction: 'Acción',
    colActor: 'Actor',
    colDetails: 'Detalles',
    weekdays: ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'],
    distance: ['Misma ciudad', 'Mismo país, otra ciudad', 'Exterior'],
    featYes: 'Sí',
    featNo: 'No',
    checksMatch: '% de las verificaciones coincide',
    percentileOf: 'percentil {n} de los cargos del banco',
    notScored: 'Sin puntaje: el modelo solo califica cargos Web y App, o no se identificó un cargo.',
    scoreNA: 'Puntaje no disponible',
    aboveThreshold: 'Sobre el umbral ({x}x): POL-ESC-ML-RISK',
    belowThresholdBy: 'Bajo el umbral ({x}x menor): sin escalación por riesgo',
    belowThreshold: 'Bajo el umbral: sin escalación por riesgo',
    highRisk: 'Riesgo alto',
    lowRisk: 'Riesgo bajo',
    scoreLine: 'Puntaje {score}, umbral {threshold} (percentil 98 de los cargos Web y App del banco). El puntaje ordena qué tan inusual es el cargo; no es una probabilidad de fraude.',
    drivers: 'Qué movió el puntaje',
    raises: '▲ sube',
    lowers: '▼ baja',
    driversNote: 'Cada cifra es el cambio del puntaje frente al mismo cargo con esa variable en su mediana.',
    memCases: 'Casos abiertos (180 días)',
    memHandoffs: 'Escalaciones a humano (180 días)',
    memRefused: 'Rechazó un bloqueo de tarjeta',
    memDistress: 'Angustia severa (30 días)',
    memDistressYes: 'Sí: escala por POL-ESC-DISTRESS',
    noHistory: 'Sin historial',
    hasHistory: 'Con historial',
    memNote: 'Registrado solo por este sistema, no es el historial de quejas del banco.',
  },
  pt: {
    title: 'Console HITL',
    agent: 'Agente',
    subtitle: 'As decisões aqui ficam registradas; nenhum dinheiro é movimentado.',
    logout: 'Sair',
    language: 'Idioma',
    tabCases: 'Casos',
    tabHandoffs: 'Escalações',
    tabLocks: 'Bloqueios',
    tabAudit: 'Auditoria',
    forbidden: 'Esta tela exige o papel de agente',
    refresh: 'Atualizar',
    refreshing: 'Atualizando...',
    none: 'nenhum',
    creditOnly: 'Somente candidatos a crédito',
    noCases: 'Não há casos.',
    colCase: 'Caso',
    colCustomer: 'Cliente',
    colTransaction: 'Transação',
    colSubcategory: 'Subcategoria',
    colStatus: 'Status',
    colClaimed: 'Contestado',
    colUsd: 'USD',
    colClauses: 'Cláusulas',
    colCreditCandidate: 'Candidato a crédito',
    colDecision: 'Decisão',
    colCreated: 'Criado',
    yes: 'sim',
    no: 'não',
    notApplicable: 'n/a',
    approve: 'Aprovar',
    reject: 'Rejeitar',
    handoffsOrder: 'Abertas primeiro, as mais recentes primeiro.',
    noHandoffs: 'Não há escalações.',
    customer: 'cliente',
    customerRequest: 'Solicitação do cliente',
    triggeringTransaction: 'Transação de origem',
    verifiedFacts: 'Fatos verificados',
    supportingEvidence: 'Evidências de suporte',
    applicableClauses: 'Cláusulas de política aplicáveis',
    secondaryClauses: 'Cláusulas secundárias',
    unresolvedQuestions: 'Perguntas pendentes para o cliente',
    cardLock: 'Bloqueio de cartão',
    creditRecommendation: 'Recomendação de crédito provisório',
    riskExplanation: 'Explicação do risco',
    caseMemory: 'Memória do caso',
    rawPacket: 'Pacote completo',
    resolving: 'Resolvendo...',
    resolve: 'Resolver',
    resolvedBy: 'Resolvida por',
    on: 'em',
    noLocks: 'Não há bloqueios de cartão.',
    colLock: 'Bloqueio',
    colProduct: 'Produto',
    colReason: 'Motivo',
    colVerified: 'Verificado',
    colConversation: 'Conversa',
    colUpdated: 'Atualizado',
    conversationId: 'Id da conversa',
    filter: 'Filtrar',
    clear: 'Limpar',
    noAudit: 'Não há registros de auditoria.',
    colWhen: 'Quando',
    colAction: 'Ação',
    colActor: 'Ator',
    colDetails: 'Detalhes',
    weekdays: ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'],
    distance: ['Mesma cidade', 'Mesmo país, outra cidade', 'Exterior'],
    featYes: 'Sim',
    featNo: 'Não',
    checksMatch: '% das verificações coincide',
    percentileOf: 'percentil {n} das cobranças do banco',
    notScored: 'Sem pontuação: o modelo avalia só cobranças Web e App, ou nenhuma cobrança foi identificada.',
    scoreNA: 'Pontuação indisponível',
    aboveThreshold: 'Acima do limite ({x}x): POL-ESC-ML-RISK',
    belowThresholdBy: 'Abaixo do limite ({x}x menor): sem escalação por risco',
    belowThreshold: 'Abaixo do limite: sem escalação por risco',
    highRisk: 'Risco alto',
    lowRisk: 'Risco baixo',
    scoreLine: 'Pontuação {score}, limite {threshold} (percentil 98 das cobranças Web e App do banco). A pontuação ordena o quão incomum é a cobrança; não é uma probabilidade de fraude.',
    drivers: 'O que moveu a pontuação',
    raises: '▲ aumenta',
    lowers: '▼ reduz',
    driversNote: 'Cada número é a mudança da pontuação frente à mesma cobrança com essa variável na mediana.',
    memCases: 'Casos abertos (180 dias)',
    memHandoffs: 'Escalações para humano (180 dias)',
    memRefused: 'Recusou um bloqueio de cartão',
    memDistress: 'Angústia severa (30 dias)',
    memDistressYes: 'Sim: escala por POL-ESC-DISTRESS',
    noHistory: 'Sem histórico',
    hasHistory: 'Com histórico',
    memNote: 'Registrado só por este sistema, não é o histórico de reclamações do banco.',
  },
  en: {
    title: 'HITL Console',
    agent: 'Agent',
    subtitle: 'Decisions here are recorded; no money moves.',
    logout: 'Log out',
    language: 'Language',
    tabCases: 'Cases',
    tabHandoffs: 'Handoffs',
    tabLocks: 'Locks',
    tabAudit: 'Audit log',
    forbidden: 'This view requires the agent role',
    refresh: 'Refresh',
    refreshing: 'Refreshing...',
    none: 'none',
    creditOnly: 'Credit candidates only',
    noCases: '{t.noCases}',
    colCase: 'Case',
    colCustomer: 'Customer',
    colTransaction: 'Transaction',
    colSubcategory: 'Subcategory',
    colStatus: 'Status',
    colClaimed: 'Claimed',
    colUsd: 'USD',
    colClauses: 'Clauses',
    colCreditCandidate: 'Credit candidate',
    colDecision: 'Decision',
    colCreated: 'Created',
    yes: 'yes',
    no: 'no',
    notApplicable: 'n/a',
    approve: 'Approve',
    reject: 'Reject',
    handoffsOrder: 'Open handoffs first, newest first.',
    noHandoffs: '{t.noHandoffs}',
    customer: 'customer',
    customerRequest: 'Customer request',
    triggeringTransaction: 'Triggering transaction',
    verifiedFacts: 'Verified facts',
    supportingEvidence: 'Supporting evidence',
    applicableClauses: 'Applicable policy clauses',
    secondaryClauses: 'Secondary clauses',
    unresolvedQuestions: 'Unresolved questions for the customer',
    cardLock: 'Card lock',
    creditRecommendation: 'Provisional credit recommendation',
    riskExplanation: 'Risk explanation',
    caseMemory: 'Case memory',
    rawPacket: 'Raw packet',
    resolving: 'Resolving...',
    resolve: 'Resolve',
    resolvedBy: 'Resolved by',
    on: 'on',
    noLocks: '{t.noLocks}',
    colLock: 'Lock',
    colProduct: 'Product',
    colReason: 'Reason',
    colVerified: 'Verified',
    colConversation: 'Conversation',
    colUpdated: 'Updated',
    conversationId: 'Conversation id',
    filter: 'Filter',
    clear: 'Clear',
    noAudit: '{t.noAudit}',
    colWhen: 'When',
    colAction: 'Action',
    colActor: 'Actor',
    colDetails: 'Details',
    weekdays: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
    distance: ['Same city', 'Same country, other city', 'Abroad'],
    featYes: 'Yes',
    featNo: 'No',
    checksMatch: '% of checks match',
    percentileOf: 'percentile {n} of bank charges',
    notScored: 'Not scored: the model rates only Web and App charges, or no charge was identified.',
    scoreNA: 'Score not available',
    aboveThreshold: 'Above the threshold ({x}x): POL-ESC-ML-RISK',
    belowThresholdBy: 'Below the threshold ({x}x lower): no risk escalation',
    belowThreshold: 'Below the threshold: no risk escalation',
    highRisk: 'High risk',
    lowRisk: 'Low risk',
    scoreLine: "Score {score}, threshold {threshold} (percentile 98 of the bank's Web and App charges). The score ranks how unusual the charge is; it is not a probability of fraud.",
    drivers: 'What moved the score',
    raises: '▲ raises',
    lowers: '▼ lowers',
    driversNote: 'Each figure is the change in the score against the same charge with that feature at its median.',
    memCases: 'Cases opened (180 days)',
    memHandoffs: 'Handoffs to a human (180 days)',
    memRefused: 'Refused a card lock',
    memDistress: 'Severe distress (30 days)',
    memDistressYes: 'Yes: escalates by POL-ESC-DISTRESS',
    noHistory: 'No history',
    hasHistory: 'Has history',
    memNote: "Recorded by this system only, not the bank's complaint history.",
  },
} satisfies Record<ConsoleLanguage, Record<string, string | string[]>>

type Labels = (typeof LABELS)['en']

/** The agent's last pick, else the browser language (Portuguese or Spanish), else English. */
function initialLanguage(): ConsoleLanguage {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY)
    if (saved === 'es' || saved === 'pt' || saved === 'en') return saved
  } catch {
    // storage blocked: fall through to the browser language
  }
  const browser = (navigator.language || '').toLowerCase()
  if (browser.startsWith('pt')) return 'pt'
  if (browser.startsWith('es')) return 'es'
  return 'en'
}

const I18n = createContext<{ t: Labels; locale: string }>({ t: LABELS.en, locale: LOCALES.en })

function useI18n() {
  return useContext(I18n)
}

function errorText(err: unknown, t: Labels): string {
  if (err instanceof ApiError && err.status === 403) return t.forbidden
  return describeError(err)
}

function fmtDate(value: string | null | undefined, locale: string): string {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(locale)
}

function fmtUsd(value: number | null | undefined, locale: string): string {
  if (value == null) return ''
  return new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' }).format(value)
}

function fmtMoney(amount: number | null | undefined, currency: string | null | undefined, locale: string): string {
  if (amount == null) return ''
  if (!currency) return amount.toFixed(2)
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

/** Shared loading state per tab: data, error, refresh. */
function useResource<T>(loader: () => Promise<T>) {
  const { t } = useI18n()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await loader())
    } catch (err) {
      setError(errorText(err, t))
    } finally {
      setLoading(false)
    }
  }, [loader, t])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { data, error, loading, refresh, setData, setError }
}

function Toolbar({ children, loading, onRefresh }: { children?: ReactNode; loading: boolean; onRefresh: () => void }) {
  const { t } = useI18n()
  return (
    <div className="toolbar">
      <div className="row-actions">{children}</div>
      <button type="button" className="btn" disabled={loading} onClick={onRefresh}>
        {loading ? t.refreshing : t.refresh}
      </button>
    </div>
  )
}

function List({ items }: { items: string[] | undefined }) {
  const { t } = useI18n()
  if (!items || items.length === 0) return <span className="muted">{t.none}</span>
  return (
    <ul className="plain-list">
      {items.map((item, i) => <li key={i}>{item}</li>)}
    </ul>
  )
}

function Json({ value }: { value: unknown }) {
  const { t } = useI18n()
  if (value == null) return <span className="muted">{t.none}</span>
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

// Discrete features of src/ml/feature_contract.py pass through the ranker; every other value is a percentile (0 to 1)
// of the bank's Web and App charges, not the raw amount or count.
function featureValue(feature: string, value: number, t: Labels): string {
  switch (feature) {
    case 'amount_has_cents':
    case 'card_kind_credit':
    case 'card_kind_debit':
      return value >= 0.5 ? t.featYes : t.featNo
    case 'day_of_week':
      return t.weekdays[Math.round(value)] ?? String(value)
    case 'address_distance_bucket':
      return t.distance[Math.round(value)] ?? String(value)
    case 'consistency_matches':
      return `${Math.round(value * 100)} ${t.checksMatch}`
    default:
      return t.percentileOf.replace('{n}', String(Math.round(value * 100)))
  }
}

interface RiskFeature {
  feature?: string
  phrase?: string
  value?: number
  contribution?: number
}

/** The risk score against the POL-ESC-ML-RISK threshold. The score ranks charges; it is not a probability of fraud. */
function RiskCard({ value }: { value: Record<string, unknown> | null | undefined }) {
  const { t } = useI18n()
  if (!value) {
    return <p className="muted">{t.notScored}</p>
  }
  const score = typeof value.score === 'number' ? value.score : null
  const threshold = typeof value.threshold === 'number' ? value.threshold : null
  const features = (Array.isArray(value.top_features) ? value.top_features : []) as RiskFeature[]
  const above = score != null && threshold != null && score >= threshold
  // Bar scale: the threshold sits at 75 % of the width so a score above it still fits.
  const scale = threshold ? threshold / 0.75 : Math.max(score ?? 0, 1)
  const pct = (x: number) => `${Math.min(100, (x / scale) * 100)}%`
  let verdict = t.scoreNA
  if (score != null && threshold != null) {
    verdict = above
      ? t.aboveThreshold.replace('{x}', (score / threshold).toFixed(1))
      : score > 0 ? t.belowThresholdBy.replace('{x}', (threshold / score).toFixed(1)) : t.belowThreshold
  }

  return (
    <div className="insight">
      <div className="insight-head">
        <span className={`pill ${above ? 'refused' : 'resolved'}`}>{above ? t.highRisk : t.lowRisk}</span>
        <span>{verdict}</span>
      </div>
      {score != null && (
        <div className="meter" role="img" aria-label={`Score ${score.toFixed(3)}, threshold ${threshold?.toFixed(3) ?? 'unknown'}`}>
          <div className={`meter-fill ${above ? 'high' : 'low'}`} style={{ width: pct(score) }} />
          {threshold != null && <div className="meter-mark" style={{ left: pct(threshold) }} />}
        </div>
      )}
      <p className="muted small">
        {t.scoreLine.replace('{score}', score?.toFixed(3) ?? 'n/a').replace('{threshold}', threshold?.toFixed(3) ?? 'n/a')}
      </p>
      {features.length > 0 && (
        <>
          <strong className="sub-label">{t.drivers}</strong>
          <ul className="drivers">
            {features.map((f, i) => {
              const c = f.contribution ?? 0
              const up = c > 0
              return (
                <li key={i} title={f.feature}>
                  <span className={`driver-dir ${up ? 'up' : 'down'}`}>{up ? t.raises : t.lowers}</span>
                  <span className="driver-name">
                    {f.phrase ?? f.feature}
                    {f.value != null && f.feature && <span className="muted">: {featureValue(f.feature, f.value, t)}</span>}
                  </span>
                  <code className="driver-delta">{up ? '+' : ''}{c.toFixed(3)}</code>
                </li>
              )
            })}
          </ul>
          <p className="muted small">{t.driversNote}</p>
        </>
      )}
    </div>
  )
}

/** What the system recorded for this customer (src/ops/store.py case_memory). Only the distress flag changes a decision. */
function CaseMemoryCard({ value }: { value: Record<string, unknown> | undefined }) {
  const { t } = useI18n()
  if (!value || Object.keys(value).length === 0) return <span className="muted">{t.none}</span>
  const cases = Number(value.prior_cases_180d ?? 0)
  const escalations = Number(value.prior_escalations_180d ?? 0)
  const refused = value.prior_lock_refused === true
  const distress = typeof value.prior_distress_max_30d === 'number' && value.prior_distress_max_30d >= 2
  const clean = cases === 0 && escalations === 0 && !refused && !distress
  const items: { label: string; text: string; flag: boolean }[] = [
    { label: t.memCases, text: String(cases), flag: cases > 0 },
    { label: t.memHandoffs, text: String(escalations), flag: escalations > 0 },
    { label: t.memRefused, text: refused ? t.featYes : t.featNo, flag: refused },
    { label: t.memDistress, text: distress ? t.memDistressYes : t.featNo, flag: distress },
  ]
  return (
    <div className="insight">
      <div className="insight-head">
        <span className={`pill ${clean ? 'resolved' : 'offered'}`}>{clean ? t.noHistory : t.hasHistory}</span>
        <span className="muted">{t.memNote}</span>
      </div>
      <ul className="chips">
        {items.map((it) => (
          <li key={it.label} className={it.flag ? 'chip flag' : 'chip'}>
            <span className="muted">{it.label}</span> <span className="chip-value">{it.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ Cases

function CasesTab() {
  const { t, locale } = useI18n()
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
      setError(errorText(err, t))
    } finally {
      setDeciding(null)
    }
  }

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <label className="checkbox">
          <input type="checkbox" checked={candidatesOnly} onChange={(e) => setCandidatesOnly(e.target.checked)} />
          {t.creditOnly}
        </label>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">{t.noCases}</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.colCase}</th>
                <th>{t.colCustomer}</th>
                <th>{t.colTransaction}</th>
                <th>{t.colSubcategory}</th>
                <th>{t.colStatus}</th>
                <th>{t.colClaimed}</th>
                <th>{t.colUsd}</th>
                <th>{t.colClauses}</th>
                <th>{t.colCreditCandidate}</th>
                <th>{t.colDecision}</th>
                <th>{t.colCreated}</th>
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
                  <td>{fmtMoney(c.claimed_amount, c.currency, locale)}</td>
                  <td>{fmtUsd(c.amount_usd, locale)}</td>
                  <td>{c.cited_clauses.join(', ')}</td>
                  <td>{c.provisional_credit_candidate ? `${t.yes} (${fmtUsd(c.provisional_credit_amount_usd, locale)})` : t.no}</td>
                  <td>
                    {!c.provisional_credit_candidate && <span className="muted">{t.notApplicable}</span>}
                    {c.provisional_credit_candidate && c.credit_decision && <span className={`pill ${c.credit_decision}`}>{c.credit_decision}</span>}
                    {c.provisional_credit_candidate && !c.credit_decision && (
                      <span className="row-actions">
                        <button type="button" className="btn btn-small btn-primary" disabled={deciding !== null} onClick={() => decide(c.case_id, 'approved')}>{t.approve}</button>
                        <button type="button" className="btn btn-small" disabled={deciding !== null} onClick={() => decide(c.case_id, 'rejected')}>{t.reject}</button>
                      </span>
                    )}
                  </td>
                  <td>{fmtDate(c.created_at, locale)}</td>
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
  const { t, locale } = useI18n()
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
      setError(errorText(err, t))
    } finally {
      setResolving(null)
    }
  }

  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh}>
        <span className="muted">{t.handoffsOrder}</span>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">{t.noHandoffs}</p>}
      <div className="stack">
        {data?.map((h) => {
          const p = h.packet ?? {}
          return (
            <details key={h.handoff_id} className="card handoff" open={h.status === 'open'}>
              <summary>
                <span className={`pill ${h.status}`}>{h.status}</span>
                <code>{h.handoff_id}</code>
                <span>{h.escalation_reason}</span>
                <span className="muted">{t.customer} <code>{h.customer_id}</code>, {fmtDate(h.created_at, locale)}</span>
              </summary>
              <div className="packet">
                <div className="field"><strong>{t.customerRequest}</strong><p>{p.customer_request || <span className="muted">{t.none}</span>}</p></div>
                <div className="field"><strong>{t.triggeringTransaction}</strong>
                  {p.triggering_transaction ? (
                    <p>
                      <code>{String(p.triggering_transaction.transaction_id ?? '')}</code>{' '}
                      {String(p.triggering_transaction.process_date ?? '')}{' '}
                      {fmtMoney(p.triggering_transaction.amount ?? null, p.triggering_transaction.currency ?? null, locale)}{' '}
                      {p.triggering_transaction.merchant_name ? String(p.triggering_transaction.merchant_name) : ''}
                    </p>
                  ) : <p className="muted">{t.none}</p>}
                </div>
                <div className="field"><strong>{t.verifiedFacts}</strong><List items={p.verified_facts} /></div>
                <div className="field"><strong>{t.supportingEvidence}</strong><List items={p.supporting_evidence} /></div>
                <div className="field"><strong>{t.applicableClauses}</strong><List items={p.applicable_policy_clauses} /></div>
                <div className="field"><strong>{t.secondaryClauses}</strong><List items={p.secondary_clauses} /></div>
                <div className="field"><strong>{t.unresolvedQuestions}</strong><List items={p.unresolved_questions_for_customer} /></div>
                <div className="field"><strong>{t.cardLock}</strong><Json value={p.card_lock} /></div>
                <div className="field"><strong>{t.creditRecommendation}</strong><Json value={p.provisional_credit_recommendation} /></div>
                <div className="field"><strong>{t.riskExplanation}</strong><RiskCard value={p.risk_explanation} /></div>
                <div className="field"><strong>{t.caseMemory}</strong><CaseMemoryCard value={p.case_memory} /></div>
                <details className="sub">
                  <summary>{t.rawPacket}</summary>
                  <Json value={h.packet} />
                </details>
                <div className="row-actions">
                  {h.status === 'open' ? (
                    <button type="button" className="btn btn-primary" disabled={resolving !== null} onClick={() => resolve(h.handoff_id)}>
                      {resolving === h.handoff_id ? t.resolving : t.resolve}
                    </button>
                  ) : (
                    <span className="muted">{t.resolvedBy} {h.resolved_by ?? t.agent} {t.on} {fmtDate(h.resolved_at, locale)}</span>
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
  const { t, locale } = useI18n()
  const loader = useCallback(() => api.consoleLocks(), [])
  const { data, error, loading, refresh } = useResource<LockRow[]>(loader)
  return (
    <>
      <Toolbar loading={loading} onRefresh={refresh} />
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">{t.noLocks}</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.colLock}</th>
                <th>{t.colCustomer}</th>
                <th>{t.colProduct}</th>
                <th>{t.colReason}</th>
                <th>{t.colStatus}</th>
                <th>{t.colVerified}</th>
                <th>{t.colConversation}</th>
                <th>{t.colCreated}</th>
                <th>{t.colUpdated}</th>
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
                  <td>{l.verified ? t.yes : t.no}</td>
                  <td><code>{l.conversation_id ?? ''}</code></td>
                  <td>{fmtDate(l.created_at, locale)}</td>
                  <td>{fmtDate(l.updated_at, locale)}</td>
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
  const { t, locale } = useI18n()
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
          <input type="text" value={filter} placeholder={t.conversationId} onChange={(e) => setFilter(e.target.value)} aria-label={t.conversationId} />
          <button type="submit" className="btn btn-small">{t.filter}</button>
          {applied && (
            <button type="button" className="btn btn-small btn-ghost" onClick={() => { setFilter(''); setApplied('') }}>{t.clear}</button>
          )}
        </form>
      </Toolbar>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {data && data.length === 0 && <p className="muted">{t.noAudit}</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.colWhen}</th>
                <th>{t.colAction}</th>
                <th>{t.colActor}</th>
                <th>{t.colVerified}</th>
                <th>{t.colConversation}</th>
                <th>{t.colCustomer}</th>
                <th>{t.colDetails}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.audit_id}>
                  <td>{fmtDate(a.created_at, locale)}</td>
                  <td>{a.action}</td>
                  <td>{a.actor}</td>
                  <td>{a.verified ? t.yes : t.no}</td>
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
  const [language, setLanguage] = useState<ConsoleLanguage>(initialLanguage)
  const t = LABELS[language]

  const pickLanguage = (lang: ConsoleLanguage) => {
    setLanguage(lang)
    try {
      localStorage.setItem(LANGUAGE_KEY, lang)
    } catch {
      // storage blocked: the pick lasts for this page only
    }
  }

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  return (
    <I18n.Provider value={{ t, locale: LOCALES[language] }}>
      <main className="page">
        <header className="page-header row">
          <div>
            <h1>{t.title}</h1>
            <p className="muted">{t.agent} <code>{session.label}</code>. {t.subtitle}</p>
          </div>
          <div className="row-actions">
            <div className="segmented" role="group" aria-label={t.language}>
              {LANGUAGES.map((lang) => (
                <button key={lang} type="button" className={lang === language ? 'active' : ''}
                  aria-pressed={lang === language} onClick={() => pickLanguage(lang)}>
                  {lang.toUpperCase()}
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-ghost" onClick={onLogout}>{t.logout}</button>
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
              {t[item.label]}
            </button>
          ))}
        </nav>

        <section className="tab-panel" role="tabpanel">
          {tab === 'cases' && <CasesTab />}
          {tab === 'handoffs' && <HandoffsTab />}
          {tab === 'locks' && <LocksTab />}
          {tab === 'audit' && <AuditTab />}
        </section>
      </main>
    </I18n.Provider>
  )
}
