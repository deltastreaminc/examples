import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'

import { signup, streamChat, validateToken } from './api'
import type { ChatMessage } from './types'

const PROMPTS = [
  'Show me the freshest high-priority stablecoin payment exceptions.',
  'What happened with the most recent invoice? Can we release the order?',
  'Customer says they paid the most recent invoice. What does the latest context say?',
  'Why is the most recent invoice blocked even though payment arrived?',
  'Find recent invoices where the payment arrived on the wrong chain.',
  'Find recent invoices where the customer underpaid or overpaid.',
  'Which payment exceptions changed most recently?',
  'Does the most recent invoice look underpaid or overpaid right now?',
]

const createId = () =>
  (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`)

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [signupMessage, setSignupMessage] = useState<string | null>(null)
  const [isValidated, setIsValidated] = useState(false)
  const [isSignupCollapsed, setIsSignupCollapsed] = useState(false)
  const [isTokenCollapsed, setIsTokenCollapsed] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isSigningUp, setIsSigningUp] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chatPanelRef = useRef<HTMLElement | null>(null)

  const canSend = useMemo(
    () => input.trim().length > 0 && !isStreaming && isValidated,
    [input, isStreaming, isValidated],
  )

  const canSignup = useMemo(() => email.trim().includes('@') && !isSigningUp, [email, isSigningUp])
  const canValidate = useMemo(() => token.trim().length > 0 && !isValidating, [token, isValidating])
  const maskedToken = useMemo(() => {
    const trimmed = token.trim()
    if (trimmed.length <= 10) {
      return trimmed
    }
    return `${trimmed.slice(0, 6)}...${trimmed.slice(-4)}`
  }, [token])

  const onSignup = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSignup) {
      return
    }
    setError(null)
    setSignupMessage(null)
    setIsSigningUp(true)
    try {
      const message = await signup(email.trim())
      setSignupMessage(message)
      setIsSignupCollapsed(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown signup error')
    } finally {
      setIsSigningUp(false)
    }
  }

  const onValidateToken = async (event: FormEvent) => {
    event.preventDefault()
    if (!canValidate) {
      return
    }
    setError(null)
    setIsValidating(true)
    try {
      await validateToken(token.trim())
      setIsValidated(true)
      setIsSignupCollapsed(true)
      setIsTokenCollapsed(true)
    } catch (err) {
      setIsValidated(false)
      setError(err instanceof Error ? err.message : 'Unknown token validation error')
    } finally {
      setIsValidating(false)
    }
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) {
      return
    }

    setError(null)
    setIsStreaming(true)

    const userMessage: ChatMessage = {
      id: createId(),
      role: 'user',
      text,
    }
    const assistantId = createId()
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      text: '',
      latestCtxTimeMs: null,
    }

    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setInput('')

    try {
      const result = await streamChat(text, token.trim(), (delta) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, text: `${m.text}${delta}` } : m)),
        )
      })

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                text: result.text || m.text,
                latestCtxTimeMs: result.latestCtxTimeMs,
              }
            : m,
        ),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setIsStreaming(false)
    }
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    await sendMessage(input)
  }

  const onClearChat = () => {
    if (isStreaming) {
      return
    }
    setMessages([])
    setInput('')
    setError(null)
  }

  useEffect(() => {
    const panel = chatPanelRef.current
    if (!panel) {
      return
    }
    panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' })
  }, [messages])

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Stablecoin Payment Ops Agent</h1>
        <p>DeltaStream context with Anthropic Sonnet 4.6 via PydanticAI</p>
        <p className="scenario-note">
          This demo represents a realistic stablecoin payment-operations workflow for support and risk teams.
          Customer invoices, merchant policy updates, wallet risk and compliance profiles, support case events,
          and simulated confirmed onchain transfers stream into DeltaStream continuously. DeltaStream then
          matches and reconciles payments, flags operational exceptions (for example wrong chain, wrong token,
          unexpected payer wallet, underpayment, overpayment, and duplicate or split transfers), and publishes
          an always-fresh operations context to materialized views. The agent does not reason over raw source
          events directly at chat time; it answers from this pre-computed context so responses stay fast,
          auditable, and tied to the latest reflected `ctx_time_ms`.
        </p>
      </header>

      <section className="auth-grid">
        {isSignupCollapsed ? (
          <section className="signup-form auth-collapsed">
            <div className="auth-title">Signup email</div>
            <div className="hint">Submitted as {email.trim()}.</div>
            {signupMessage ? <div className="hint">{signupMessage}</div> : null}
            <button type="button" className="link-button" onClick={() => setIsSignupCollapsed(false)}>
              Edit email
            </button>
          </section>
        ) : (
          <form className="signup-form" onSubmit={onSignup}>
            <label htmlFor="signup-email">Signup email</label>
            <div className="inline-form">
              <input
                id="signup-email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                disabled={isSigningUp}
              />
              <button type="submit" disabled={!canSignup}>
                {isSigningUp ? 'Submitting...' : 'Sign up'}
              </button>
            </div>
            {signupMessage ? <div className="hint">{signupMessage}</div> : null}
          </form>
        )}

        {isTokenCollapsed ? (
          <section className="token-form auth-collapsed">
            <div className="auth-title-row">
              <div className="auth-title">Access token</div>
              <span className="status-badge">Validated</span>
            </div>
            <div className="hint">Token {maskedToken} validated for Anthropic and DeltaStream MCP.</div>
            <button type="button" className="link-button" onClick={() => setIsTokenCollapsed(false)}>
              Edit token
            </button>
          </section>
        ) : (
          <form className="token-form" onSubmit={onValidateToken}>
            <label htmlFor="api-token">Access token</label>
            <div className="inline-form">
              <input
                id="api-token"
                value={token}
                onChange={(event) => {
                  setToken(event.target.value)
                  setIsValidated(false)
                }}
                placeholder="Paste token from your confirmation email"
                disabled={isValidating}
              />
              <button type="submit" disabled={!canValidate}>
                {isValidating ? 'Checking...' : 'Validate token'}
              </button>
            </div>
            <div className="hint">
              {isValidated
                ? 'Token validated for Anthropic and DeltaStream MCP.'
                : 'Validate token before starting chat.'}
            </div>
          </form>
        )}
      </section>

      <section className="prompt-strip" aria-label="Demo prompts">
        {PROMPTS.map((prompt) => (
          <button key={prompt} onClick={() => void sendMessage(prompt)} disabled={isStreaming}>
            {prompt}
          </button>
        ))}
      </section>

      <main ref={chatPanelRef} className="chat-panel">
        {messages.length === 0 ? (
          <div className="empty-state">
            Ask about invoices, exceptions, risk/compliance state, or release readiness.
          </div>
        ) : null}

        {messages.map((message) => (
          <article key={message.id} className={`message ${message.role}`}>
            <div className="meta">{message.role === 'user' ? 'You' : 'Agent'}</div>
            <pre>{message.text}</pre>
            {message.role === 'assistant' && message.latestCtxTimeMs ? (
              <div className="freshness">
                ctx_time_ms: {message.latestCtxTimeMs} (latest reflected source event timestamp)
              </div>
            ) : null}
          </article>
        ))}
      </main>

      <form className="chat-input" onSubmit={onSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about an invoice or payment exception..."
          disabled={isStreaming || !isValidated}
        />
        <button
          type="button"
          className="secondary-button"
          onClick={onClearChat}
          disabled={isStreaming || messages.length === 0}
        >
          Clear chat
        </button>
        <button type="submit" disabled={!canSend}>
          {isStreaming ? 'Streaming...' : 'Send'}
        </button>
      </form>

      {error ? <div className="error">Error: {error}</div> : null}
    </div>
  )
}
