import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'

import { PartialStreamError, signup, streamChat, validateToken } from './api'
import type { ChatMessage, LlmTimingEvent, SqlStatement } from './types'

function DeltaStreamLogo() {
  return (
    <svg
      className="brand-logo"
      viewBox="0 0 133 21"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="DeltaStream"
      role="img"
    >
      <path d="M13.9544 5.2893L13.956 5.29213V5.28995L13.9544 5.2893Z" fill="#0A042A" />
      <path d="M13.9544 5.2893L10.9323 0.0539958C10.8908 -0.0179986 10.7861 -0.0179986 10.7425 0.0539958L9.02551 3.02758C9.0037 3.06685 9.03424 3.11485 9.07788 3.1083C9.33095 3.0734 9.88072 3.07558 10.7119 3.47264C11.0587 3.63879 11.4936 3.90697 11.9591 4.19395C12.6176 4.59999 13.3372 5.04366 13.9544 5.2893Z" fill="#0A042A" />
      <path d="M22.0434 19.3049C18.4001 21.2313 14.1873 20.6728 9.05388 18.1595V18.1573C4.52477 15.9408 2.22968 16.9836 0.183293 18.766C0.0894818 18.8467 -0.0457804 18.7376 0.0153058 18.6307C0.757066 17.3457 1.58827 15.908 1.58827 15.908L2.6791 14.0165C2.69889 13.9885 2.71743 13.9605 2.73472 13.9343L2.75109 13.9096C3.58012 12.677 5.75086 11.5578 10.3345 13.7569C15.0774 16.0324 17.2569 16.5865 19.7527 15.3343L22.0434 19.3049Z" fill="#0A042A" />
      <path d="M10.4479 10.1834C13.2099 11.5513 16.4475 13.0653 17.9855 12.2734L15.8039 8.49261C14.5269 8.39111 13.5608 7.88173 12.4085 7.27424C12.0253 7.0722 11.6215 6.85929 11.1788 6.64694C9.36803 5.77864 8.07213 5.52557 7.40237 6.1408C7.21693 6.31096 6.96604 6.6513 6.69988 7.05709L6.46862 7.45851L5.34944 9.39582C5.32107 9.44381 5.37562 9.49835 5.42361 9.46999C6.44681 8.84386 7.82779 8.88531 10.4479 10.1834Z" fill="#0A042A" />
      <path d="M32.1506 14.8404H34.7856C37.2513 14.8404 39.1146 12.9394 39.1146 10.135C39.1146 7.33056 37.2513 5.42956 34.7856 5.42956H32.1506V14.8404ZM30.1743 16.7226V3.54739H34.7856C38.3618 3.54739 41.0909 6.29536 41.0909 10.135C41.0909 13.9746 38.3618 16.7226 34.7856 16.7226H30.1743Z" fill="#0A042A" />
      <path d="M44.2002 11.2643H49.7526C49.5456 9.75856 48.5292 8.72336 47.0234 8.72336C45.4236 8.72336 44.4825 9.75856 44.2002 11.2643ZM49.2821 13.9935H51.2583C50.8066 15.2169 49.4703 16.9108 47.0234 16.9108C44.2943 16.9108 42.318 14.9345 42.318 12.0172C42.318 9.0998 44.2943 7.12352 47.0234 7.12352C49.5644 7.12352 51.5407 9.0998 51.5407 11.7348C51.5407 12.0172 51.503 12.243 51.4842 12.4124L51.4466 12.6759H44.2002C44.4072 14.2758 45.5177 15.311 47.0234 15.311C48.1528 15.311 48.9809 14.6522 49.2821 13.9935Z" fill="#0A042A" />
      <path d="M53.2405 16.7226V3.54739H55.1227V16.7226H53.2405Z" fill="#0A042A" />
      <path d="M58.0445 14.7463V9.0998H56.5387V7.31173H58.0445V4.67669H59.9266V7.31173H62.0911V9.0998H59.9266V14.464C59.9266 14.8404 60.1148 15.0286 60.4913 15.0286H62.0911V16.7226H60.1148C58.7785 16.7226 58.0445 15.9697 58.0445 14.7463Z" fill="#0A042A" />
      <path d="M69.5389 16.7226L69.3507 15.6874H69.2566C69.0684 15.9321 68.8425 16.1391 68.579 16.3085C68.1273 16.6097 67.4121 16.9108 66.4334 16.9108C64.363 16.9108 63.0454 15.7062 63.0454 13.9935C63.0454 12.1113 64.2689 10.8879 66.9039 10.8879H69.2566V10.6996C69.2566 9.47623 68.5038 8.72336 67.2803 8.72336C65.9628 8.72336 65.3982 9.47623 65.3041 10.0409H63.4219C63.516 8.45986 64.9276 7.12352 67.2803 7.12352C69.746 7.12352 71.1388 8.51632 71.1388 10.6996V16.7226H69.5389ZM69.2566 12.77V12.3936H66.998C65.5676 12.3936 64.9276 13.0524 64.9276 13.8993C64.9276 14.7463 65.4923 15.311 66.6216 15.311C68.3344 15.311 69.2566 14.3699 69.2566 12.77Z" fill="#0A042A" />
      <path d="M74.3872 12.7699H76.3635C76.3635 13.9933 77.6057 15.1226 79.5632 15.1226C81.7277 15.1226 82.5747 14.2757 82.5747 13.1463C82.5747 12.1864 81.8218 11.5465 80.3161 11.2642L77.7751 10.7936C75.6859 10.4172 74.6695 9.1185 74.6695 7.31161C74.6695 5.14711 76.4576 3.45316 79.375 3.45316C82.6688 3.45316 84.3627 5.33533 84.3627 7.68805H82.3864C82.3864 6.46463 81.2571 5.33533 79.375 5.33533C77.5869 5.33533 76.6458 6.25759 76.6458 7.31161C76.6458 8.15859 77.1916 8.81735 78.6221 9.09968L80.6925 9.47611C83.3464 9.94666 84.5509 11.0571 84.5509 13.1463C84.5509 15.3109 82.857 17.0048 79.5632 17.0048C76.2694 17.0048 74.3872 15.1226 74.3872 12.7699Z" fill="#0A042A" />
      <path d="M86.6302 14.8403V9.19378H85.1244V7.40572H86.6302V4.77068H88.5123V7.40572H90.6768V9.19378H88.5123V14.558C88.5123 14.9344 88.7006 15.1226 89.077 15.1226H90.6768V16.8166H88.7006C87.3642 16.8166 86.6302 16.0637 86.6302 14.8403Z" fill="#0A042A" />
      <path d="M92.3752 16.8166V7.40572H93.975L94.1633 8.2527H94.2574C94.5773 7.89508 94.8785 7.40572 96.0454 7.40572H97.7394V9.09968H96.2337C94.9161 9.09968 94.2574 9.75844 94.2574 11.0571V16.8166H92.3752Z" fill="#0A042A" />
      <path d="M99.8252 11.3583H105.378C105.171 9.85255 104.154 8.81735 102.648 8.81735C101.049 8.81735 100.108 9.85255 99.8252 11.3583ZM104.907 14.0874H106.883C106.432 15.3109 105.095 17.0048 102.648 17.0048C99.9193 17.0048 97.9431 15.0285 97.9431 12.1112C97.9431 9.19379 99.9193 7.2175 102.648 7.2175C105.189 7.2175 107.166 9.19379 107.166 11.8288C107.166 12.1112 107.128 12.337 107.109 12.5064L107.072 12.7699H99.8252C100.032 14.3698 101.143 15.405 102.648 15.405C103.778 15.405 104.606 14.7462 104.907 14.0874Z" fill="#0A042A" />
      <path d="M114.888 16.8166L114.7 15.7814H114.606C114.418 16.0261 114.192 16.2331 113.929 16.4025C113.477 16.7037 112.762 17.0048 111.783 17.0048C109.713 17.0048 108.395 15.8002 108.395 14.0874C108.395 12.2053 109.618 10.9819 112.253 10.9819H114.606V10.7936C114.606 9.57022 113.853 8.81735 112.63 8.81735C111.312 8.81735 110.748 9.57022 110.654 10.1349H108.771C108.866 8.55385 110.277 7.2175 112.63 7.2175C115.096 7.2175 116.488 8.61031 116.488 10.7936V16.8166H114.888ZM114.606 12.864V12.4876H112.348C110.917 12.4876 110.277 13.1463 110.277 13.9933C110.277 14.8403 110.842 15.405 111.971 15.405C113.684 15.405 114.606 14.4639 114.606 12.864Z" fill="#0A042A" />
      <path d="M118.468 16.8166V7.40572H120.162L120.35 8.34681H120.444C120.632 8.13977 120.858 7.95155 121.103 7.78216C121.536 7.49983 122.138 7.2175 122.891 7.2175C123.851 7.2175 124.472 7.55629 124.867 7.87626C125.093 8.0833 125.281 8.29034 125.432 8.53502H125.526C125.714 8.29034 125.959 8.0833 126.26 7.87626C126.768 7.55629 127.521 7.2175 128.631 7.2175C130.589 7.2175 132.019 8.72324 132.019 10.8689V16.8166H130.137V10.8877C130.137 9.66433 129.384 8.91146 128.255 8.91146C127.107 8.91146 126.184 9.75844 126.184 10.8877V16.8166H124.302V10.8877C124.302 9.66433 123.549 8.91146 122.42 8.91146C121.272 8.91146 120.35 9.75844 120.35 10.8877V16.8166H118.468Z" fill="#0A042A" />
    </svg>
  )
}

const PROMPTS = [
  'What is moving right now on Polymarket?',
  'Give me the top live signals right now.',
  'Which markets show strong buy pressure?',
  'Which markets look large-fill-driven?',
  'Give me the freshest signals instead of the highest score.',
  'Who is driving activity in this market?',
  'Show recent fills behind this signal.',
]

const createId = () =>
  globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sqlStatements, setSqlStatements] = useState<SqlStatement[]>([])
  const [isSqlCollapsed, setIsSqlCollapsed] = useState(true)
  const [llmTimingEvents, setLlmTimingEvents] = useState<LlmTimingEvent[]>([])
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
  const [tokenError, setTokenError] = useState<string | null>(null)
  const chatPanelRef = useRef<HTMLElement | null>(null)
  const autoValidatedTokenRef = useRef<string | null>(null)

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

  const runTokenValidation = async (rawToken: string) => {
    const trimmedToken = rawToken.trim()
    if (!trimmedToken || isValidating) {
      return
    }
    setError(null)
    setTokenError(null)
    setIsValidating(true)
    try {
      await validateToken(trimmedToken)
      setIsValidated(true)
      setIsSignupCollapsed(true)
      setIsTokenCollapsed(true)
    } catch (err) {
      setIsValidated(false)
      setTokenError(err instanceof Error ? err.message : 'Unknown token validation error')
    } finally {
      setIsValidating(false)
    }
  }

  const onValidateToken = async (event: FormEvent) => {
    event.preventDefault()
    if (!canValidate) {
      return
    }
    await runTokenValidation(token)
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
    }

    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setSqlStatements([])
    setIsSqlCollapsed(true)
    setLlmTimingEvents([])
    setInput('')

    try {
      const result = await streamChat(
        text,
        token.trim(),
        (delta) => {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, text: `${message.text}${delta}` } : message,
            ),
          )
        },
        (statement) => {
          setSqlStatements((prev) => [...prev, statement])
        },
        () => {},
        (timing) => {
          setLlmTimingEvents((prev) => [...prev, timing])
        },
        () => {
          // reset: clear any partially streamed answer before a new candidate
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, text: '' } : message,
            ),
          )
        },
      )

      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                text: result.text || message.text,
              }
            : message,
        ),
      )
    } catch (err) {
      if (err instanceof PartialStreamError) {
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  text: err.partialText || message.text,
                }
              : message,
          ),
        )
        setError(`Response stream interrupted. Showing partial response. ${err.message}`)
        return
      }
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

  useEffect(() => {
    const params = new URLSearchParams(globalThis.location.search)
    const accessToken = params.get('access_token')?.trim()
    if (!accessToken) {
      return
    }
    setToken((currentToken) => (currentToken ? currentToken : accessToken))
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(globalThis.location.search)
    const accessToken = params.get('access_token')?.trim()
    if (!accessToken || isValidated || isValidating) {
      return
    }
    if (autoValidatedTokenRef.current === accessToken) {
      return
    }
    if (token.trim() !== accessToken) {
      return
    }
    autoValidatedTokenRef.current = accessToken
    void runTokenValidation(accessToken)
  }, [isValidated, isValidating, token])

  return (
    <div className="page-shell">
      <header className="topbar">
        <a className="brand-mark" href="https://www.deltastream.io/" target="_blank" rel="noreferrer">
          <DeltaStreamLogo />
          <div>
            <div className="brand-name">DeltaStream</div>
            <div className="brand-subtitle">The Real-Time Context Engine for Agents</div>
          </div>
        </a>
      </header>

      <main className="app-shell">
        <section className="hero-panel demo-panel">
          <div className="hero-copy">
            <div className="eyebrow">Polymarket Live Signal Radar Demo</div>
            <h1>Explain what is moving on Polymarket right now.</h1>
            <p className="hero-lede">
              This demo uses DeltaStream-precomputed context from Goldsky Polymarket streams and Gamma market
              metadata. Answers stay grounded in fresh context, and freshness is anchored to <code>ctx_time_ms</code>.
            </p>
          </div>
          <div className="hero-sidecar compact-sidecar">
            <article className="signal-card signal-card-primary">
              <div className="signal-label">Broad briefing</div>
              <div className="signal-title">Top live signals</div>
              <p>Broad summaries, buy or sell pressure, activity, ranking, and large-fill-driven signals.</p>
            </article>
            <article className="signal-card">
              <div className="signal-label">Drill-down</div>
              <div className="signal-title">Drivers and evidence</div>
              <p>Used for driver analysis, raw fill evidence, and clearer market context when you ask for it.</p>
            </article>
          </div>
        </section>

        <section className="auth-grid">
          {isSignupCollapsed ? (
            <section className="signup-form auth-collapsed">
              <div className="card-kicker">Access setup</div>
              <div className="auth-title">Signup email</div>
              <div className="hint">Submitted as {email.trim()}.</div>
              {signupMessage ? <div className="hint">{signupMessage}</div> : null}
            <button type="button" className="link-button" onClick={() => setIsSignupCollapsed(false)}>
              Edit email
            </button>
          </section>
        ) : (
          <form className="signup-form" onSubmit={onSignup}>
            <div className="card-kicker">Access setup</div>
            <h3>Request demo access</h3>
            <p className="auth-copy">Enter your email to receive the demo signup and access instructions.</p>
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
            <div className="card-kicker">Access setup</div>
            <div className="auth-title-row">
              <div className="auth-title">Access token</div>
              <span className="status-badge">Validated</span>
            </div>
            <div className="hint">Token {maskedToken} validated for the model provider and DeltaStream MCP.</div>
            <button type="button" className="link-button" onClick={() => setIsTokenCollapsed(false)}>
              Edit token
            </button>
          </section>
        ) : (
          <form className="token-form" onSubmit={onValidateToken}>
            <div className="card-kicker">Access setup</div>
            <h3>Validate your token</h3>
            <p className="auth-copy">Paste the access token from your confirmation email before starting chat.</p>
            {tokenError ? <div className="error form-error">Error: {tokenError}</div> : null}
            <label htmlFor="api-token">Access token</label>
            <div className="inline-form">
              <input
                id="api-token"
                value={token}
                onChange={(event) => {
                  setToken(event.target.value)
                  setIsValidated(false)
                  setTokenError(null)
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
                ? 'Token validated for the model provider and DeltaStream MCP.'
                : 'Validate token before starting chat.'}
            </div>
          </form>
        )}
        </section>

        <section className="auth-context-card">
          <div className="feature-kicker">Runtime behavior</div>
          <h2>How the demo answers</h2>
          <p>
            The app fetches only the prepared context needed for the current question. It does not scan raw
            streaming events at chat time, and it keeps answers tied to the latest reflected event time.
          </p>
          <ul className="context-list">
            <li>Broad briefings focus on the strongest current signals</li>
            <li>Driver questions narrow into who is behind a move</li>
            <li>Evidence questions show recent raw examples when needed</li>
          </ul>
        </section>

        <section className="prompt-panel">
          <div>
            <div className="feature-kicker">Prompt starters</div>
            <h2>Try a few common demo questions.</h2>
          </div>
          <div className="prompt-strip" aria-label="Demo prompts">
            {PROMPTS.map((prompt) => (
              <button key={prompt} onClick={() => void sendMessage(prompt)} disabled={isStreaming || !isValidated}>
                {prompt}
              </button>
            ))}
          </div>
        </section>

        <section className="auth-context-card">
          <div className="feature-kicker">DeltaStream SQL</div>
          <div className="section-header-row">
            <h2>Executed during this request</h2>
            <button
              type="button"
              className="link-button"
              onClick={() => setIsSqlCollapsed((current) => !current)}
            >
              {isSqlCollapsed ? 'Expand' : 'Collapse'}
            </button>
          </div>
          {isSqlCollapsed ? (
            <p className="auth-copy">
              {sqlStatements.length === 0
                ? 'SQL statements executed through the DeltaStream MCP toolset will appear here.'
                : `${sqlStatements.length} SQL statement${sqlStatements.length === 1 ? '' : 's'} captured for this request.`}
            </p>
          ) : sqlStatements.length === 0 ? (
            <p className="auth-copy">SQL statements executed through the DeltaStream MCP toolset will appear here.</p>
          ) : (
            <div className="sql-list">
              {sqlStatements.map((statement) => (
                <pre key={statement.id} className="sql-block">
                  {statement.statement}
                </pre>
              ))}
            </div>
          )}
        </section>

        <section className="auth-context-card">
          <div className="feature-kicker">LLM timing</div>
          <h2>Model latency during this request</h2>
          {llmTimingEvents.length === 0 ? (
            <p className="auth-copy">Attempt and total LLM timing metrics will appear here during each request.</p>
          ) : (
            <div className="timing-list">
              {llmTimingEvents.map((event, index) => (
                <div key={`${event.kind}-${index}`} className="timing-row">
                  <div className="timing-label">
                    {event.kind === 'attempt' ? `Attempt ${event.attempt ?? index + 1}` : 'Total'}
                  </div>
                  <div className="timing-value">{(event.durationMs / 1000).toFixed(2)}s</div>
                  <div className="timing-meta">
                    {event.kind === 'attempt'
                      ? event.accepted
                        ? 'accepted'
                        : 'retry'
                      : `${event.attempts ?? 1} attempts`}
                    {typeof event.outputChars === 'number' ? `, ${event.outputChars} chars` : ''}
                    {event.kind === 'summary' && typeof event.hadDataQuery === 'boolean'
                      ? event.hadDataQuery
                        ? ', data queried'
                        : ', no data query'
                      : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="chat-shell">
          <div className="chat-header-row">
            <div>
              <div className="feature-kicker">Chat</div>
              <h2>Live briefing console</h2>
            </div>
            <div className="chat-header-meta">Streaming answers from DeltaStream context</div>
          </div>

          <main ref={chatPanelRef} className="chat-panel">
            {messages.length === 0 ? (
              <div className="empty-state">
                Ask for a live briefing, strongest buy or sell pressure, large-fill-driven markets, or who is
                driving activity in a specific market.
              </div>
            ) : null}

            {messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="meta">{message.role === 'user' ? 'You' : 'Agent'}</div>
                {message.role === 'assistant' && isStreaming && !message.text ? (
                  <div className="thinking-state">Thinking...</div>
                ) : (
                  <pre>{message.text}</pre>
                )}
              </article>
            ))}
          </main>

          <form className="chat-input" onSubmit={onSubmit}>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask what is moving on Polymarket right now..."
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
        </section>

        {error ? <div className="error">Error: {error}</div> : null}
      </main>
    </div>
  )
}
