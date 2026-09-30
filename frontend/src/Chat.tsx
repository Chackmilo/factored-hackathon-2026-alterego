import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, describeError, type Language, type Session, type TurnResult } from './api'

interface Props {
  session: Session
  onLogout: () => void
}

interface ChatMessage {
  id: number
  role: 'customer' | 'assistant'
  text: string
  turn?: TurnResult
}

const LABELS: Record<Language, Record<string, string>> = {
  es: {
    title: 'Disputas de cargos',
    subtitle: 'Cuéntanos qué cargo no reconoces.',
    placeholder: 'Escribe tu mensaje...',
    send: 'Enviar',
    newConversation: 'Nueva conversación',
    logout: 'Salir',
    language: 'Idioma',
    state: 'Estado',
    outcome: 'Resultado',
    clauses: 'Cláusulas',
    caseId: 'Caso',
    handoffId: 'Escalación',
    yes: 'Sí',
    no: 'No',
    pickCharge: 'Elige el cargo:',
    lockQuestion: '¿Bloqueamos la tarjeta de forma preventiva?',
    sending: 'Enviando...',
    empty: 'Aún no hay mensajes. Describe el cargo que no reconoces (fecha, monto, comercio).',
    customer: 'Cliente',
  },
  pt: {
    title: 'Contestação de cobranças',
    subtitle: 'Conte-nos qual cobrança você não reconhece.',
    placeholder: 'Escreva sua mensagem...',
    send: 'Enviar',
    newConversation: 'Nova conversa',
    logout: 'Sair',
    language: 'Idioma',
    state: 'Estado',
    outcome: 'Resultado',
    clauses: 'Cláusulas',
    caseId: 'Caso',
    handoffId: 'Escalação',
    yes: 'Sim',
    no: 'Não',
    pickCharge: 'Escolha a cobrança:',
    lockQuestion: 'Bloqueamos o cartão de forma preventiva?',
    sending: 'Enviando...',
    empty: 'Ainda não há mensagens. Descreva a cobrança que você não reconhece (data, valor, estabelecimento).',
    customer: 'Cliente',
  },
}

function formatAmount(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

export default function Chat({ session, onLogout }: Props) {
  const [language, setLanguage] = useState<Language>('es')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nextId = useRef(1)
  const endRef = useRef<HTMLDivElement>(null)

  const t = LABELS[language]
  const lastTurn = [...messages].reverse().find((m) => m.turn)?.turn ?? null
  const showCandidates = lastTurn !== null && lastTurn.state === 'awaiting_clarification' && lastTurn.candidates.length > 0
  const showLockButtons = lastTurn !== null && lastTurn.state === 'awaiting_lock_confirmation' && (lastTurn.lock_offer !== null || lastTurn.lock_status === 'offered')

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, busy])

  const reset = () => {
    setConversationId(null)
    setMessages([])
    setInput('')
    setError(null)
  }

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError(null)
    setMessages((prev) => [...prev, { id: nextId.current++, role: 'customer', text: trimmed }])
    setInput('')
    try {
      // The conversation is created lazily so the language toggle applies to it.
      let cid = conversationId
      if (!cid) {
        const conv = await api.startConversation(language)
        cid = conv.conversation_id
        setConversationId(cid)
      }
      const turn = await api.sendMessage(cid, trimmed)
      setMessages((prev) => [...prev, { id: nextId.current++, role: 'assistant', text: turn.reply, turn }])
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void send(input)
  }

  return (
    <main className="page chat-page">
      <header className="page-header row">
        <div>
          <h1>{t.title}</h1>
          <p className="muted">
            {t.subtitle} {t.customer}: <code>{session.customer_id}</code>
          </p>
        </div>
        <div className="row-actions">
          <div className="segmented" role="group" aria-label={t.language}>
            {(['es', 'pt'] as Language[]).map((lang) => (
              <button
                key={lang}
                type="button"
                className={lang === language ? 'active' : ''}
                disabled={conversationId !== null}
                title={conversationId ? t.newConversation : undefined}
                onClick={() => setLanguage(lang)}
              >
                {lang.toUpperCase()}
              </button>
            ))}
          </div>
          <button type="button" className="btn" onClick={reset}>{t.newConversation}</button>
          <button type="button" className="btn btn-ghost" onClick={onLogout}>{t.logout}</button>
        </div>
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      <section className="chat-log" aria-live="polite">
        {messages.length === 0 && <p className="muted chat-empty">{t.empty}</p>}
        {messages.map((m) => (
          <div key={m.id} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>{m.text}</div>
          </div>
        ))}
        {busy && (
          <div className="bubble-row assistant">
            <div className="bubble assistant muted">{t.sending}</div>
          </div>
        )}
        <div ref={endRef} />
      </section>

      {showCandidates && lastTurn && (
        <section className="options">
          <p className="muted">{t.pickCharge}</p>
          <div className="stack">
            {lastTurn.candidates.map((c, i) => (
              <button key={c.transaction_id} type="button" className="btn btn-block option" disabled={busy} onClick={() => send(String(i + 1))}>
                <span className="option-index">{i + 1}</span>
                <span className="option-body">
                  <span>{c.process_date}, {formatAmount(c.amount, c.currency)}</span>
                  <span className="muted">{c.merchant_name}{c.transaction_status ? `, ${c.transaction_status}` : ''}</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {showLockButtons && (
        <section className="options">
          <p className="muted">{t.lockQuestion}</p>
          <div className="row-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => send(t.yes)}>{t.yes}</button>
            <button type="button" className="btn" disabled={busy} onClick={() => send(t.no)}>{t.no}</button>
          </div>
        </section>
      )}

      <form className="composer" onSubmit={submit}>
        <input
          type="text"
          value={input}
          maxLength={2000}
          placeholder={t.placeholder}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          aria-label={t.placeholder}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>{t.send}</button>
      </form>

      {lastTurn && (
        <footer className="status-line">
          <span><strong>{t.state}:</strong> {lastTurn.state}</span>
          {lastTurn.policy_outcome && <span><strong>{t.outcome}:</strong> {lastTurn.policy_outcome}</span>}
          {lastTurn.cited_clauses.length > 0 && <span><strong>{t.clauses}:</strong> {lastTurn.cited_clauses.join(', ')}</span>}
          {lastTurn.case_id && <span><strong>{t.caseId}:</strong> <code>{lastTurn.case_id}</code></span>}
          {lastTurn.handoff_id && <span><strong>{t.handoffId}:</strong> <code>{lastTurn.handoff_id}</code></span>}
        </footer>
      )}
    </main>
  )
}
