import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { PartialStreamError, signup, streamChat, validateToken } from './api'
import type { ChatMessage, LlmTimingEvent, SqlStatement } from './types'

declare global {
  interface Window {
    __BUILD_INFO__?: {
      buildDate?: string
      buildMarker?: string
    }
  }
}

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
  'What changed across Polymarket in the last two hours?',
  'What markets deserve attention right now on Polymarket?',
  'Which live signals look strongest right now?',
  'Where is the most unusual activity showing up right now?',
  'Which observed wallets are contributing most?',
  'Show me the recent fills supporting that explanation.',
  'Explain all of this like I am 12.',
]

const createId = () =>
  globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`

const formatDuration = (durationMs: number) => {
  if (durationMs >= 1000) {
    return `${(durationMs / 1000).toFixed(1)}s`
  }
  return `${Math.round(durationMs)}ms`
}

const buildInfo = globalThis.window?.__BUILD_INFO__

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sqlStatements, setSqlStatements] = useState<SqlStatement[]>([])
  const [isSqlCollapsed, setIsSqlCollapsed] = useState(true)
  const [llmTimingEvents, setLlmTimingEvents] = useState<LlmTimingEvent[]>([])
  const [followUps, setFollowUps] = useState<string[]>([])
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
  // Auto-scroll control: keep the console pinned to the bottom only while the
  // user is already there. If they scroll up to read, stop following; if they
  // scroll back down, resume. Selecting text suppresses auto-scroll entirely.
  const stickToBottomRef = useRef(true)
  const isSelectingRef = useRef(false)
  // Stable per-conversation id so the backend can thread prior turns into the
  // agent (follow-ups like "that market" resolve against earlier answers).
  // Regenerated on "Clear chat" to start a fresh conversation.
  const conversationIdRef = useRef<string>(createId())

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
  const hasMessages = messages.length > 0

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

    // Sending a new prompt should always snap to the fresh turn, even if the
    // user had scrolled up during a previous answer.
    stickToBottomRef.current = true
    isSelectingRef.current = false
    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setSqlStatements([])
    setIsSqlCollapsed(true)
    setLlmTimingEvents([])
    setFollowUps([])
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
        conversationIdRef.current,
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
      setFollowUps(result.followUps)
    } catch (err) {
      setFollowUps([])
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

  const onInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }
    event.preventDefault()
    if (canSend) {
      void sendMessage(input)
    }
  }

  const onClearChat = () => {
    if (isStreaming) {
      return
    }
    // Start a fresh conversation so cleared turns aren't threaded into the agent.
    conversationIdRef.current = createId()
    setMessages([])
    setInput('')
    setFollowUps([])
    setError(null)
  }

  // Distance (px) from the bottom within which we consider the user "pinned"
  // and keep following new content.
  const STICK_THRESHOLD_PX = 40

  const onChatScroll = () => {
    const panel = chatPanelRef.current
    if (!panel) {
      return
    }
    const distanceFromBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight
    stickToBottomRef.current = distanceFromBottom <= STICK_THRESHOLD_PX
  }

  // Suppress auto-scroll while the user has an active text selection inside the
  // console (so copying mid-stream isn't interrupted, even at the bottom).
  useEffect(() => {
    const onSelectionChange = () => {
      const panel = chatPanelRef.current
      const selection = globalThis.getSelection?.()
      if (!panel || !selection || selection.isCollapsed || selection.rangeCount === 0) {
        isSelectingRef.current = false
        return
      }
      const anchor = selection.anchorNode
      isSelectingRef.current = anchor != null && panel.contains(anchor)
    }
    document.addEventListener('selectionchange', onSelectionChange)
    return () => document.removeEventListener('selectionchange', onSelectionChange)
  }, [])

  useEffect(() => {
    const panel = chatPanelRef.current
    if (!panel) {
      return
    }
    if (!stickToBottomRef.current || isSelectingRef.current) {
      return
    }
    // Instant (not smooth) so the viewport tracks streamed tokens without a
    // compounding animation that fights rapid updates.
    panel.scrollTo({ top: panel.scrollHeight, behavior: 'auto' })
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

  const latestTiming = llmTimingEvents[llmTimingEvents.length - 1]
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')

  const renderMessageBody = (message: ChatMessage) => {
    if (message.role === 'assistant') {
      return (
        <div className="message-markdown">
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
      )
    }

    return <pre>{message.text}</pre>
  }

  return (
    <div className="page-shell">
      <header className="topbar">
        <a className="brand-mark" href="https://www.deltastream.io/" target="_blank" rel="noreferrer">
          <DeltaStreamLogo />
        </a>
        <div className="product-mark" aria-label="Product name">
          <span>Polymarket</span>
          <strong>Signal Radar</strong>
        </div>
        {buildInfo?.buildDate || buildInfo?.buildMarker ? (
          <div className="build-badge" aria-label="Running image build info">
            <span>Running build</span>
            <strong>{buildInfo.buildMarker || 'unknown'}</strong>
            {buildInfo.buildDate ? <em>{buildInfo.buildDate}</em> : null}
          </div>
        ) : null}
        <div className="topbar-status">
          <span className={isValidated ? 'status-dot online' : 'status-dot'} />
          {isValidated ? 'Demo access active' : 'Validate access to chat'}
        </div>
      </header>

      <main className="app-shell">
        <section className="hero-panel">
          <div className="hero-copy">
            <div className="eyebrow">/ Polymarket intelligence console /</div>
            <h1>Track live Polymarket moves before they get noisy.</h1>
            <p className="hero-lede">
              Ask for fresh movers, unusual wallet activity, buy or sell pressure, and the fills behind a signal. The
              radar keeps every answer tied to the latest reflected market context.
            </p>
            <div className="powered-by">Powered by DeltaStream real-time context</div>
          </div>
          <div className="hero-sidecar" aria-label="Demo data path">
            <div className="flow-step">Trades</div>
            <div className="flow-line" />
            <div className="flow-step flow-step-strong">Signal radar</div>
            <div className="flow-line" />
            <div className="flow-step">Briefing</div>
          </div>
        </section>

        <section className="workspace-grid">
          <aside className="side-rail" aria-label="Demo setup and context">
            <section className="rail-card setup-card">
              <div className="card-kicker">/ access setup /</div>
              {isSignupCollapsed ? (
                <div className="auth-collapsed">
                  <div className="auth-title-row">
                    <div>
                      <div className="auth-title">Signup email</div>
                      <div className="auth-value">{email.trim() || 'Email submitted'}</div>
                    </div>
                    <span className="status-badge">Sent</span>
                  </div>
                  {signupMessage ? <div className="hint">{signupMessage}</div> : null}
                  <button type="button" className="link-button" onClick={() => setIsSignupCollapsed(false)}>
                    Edit email
                  </button>
                </div>
              ) : (
                <form className="stack-form" onSubmit={onSignup}>
                  <h3>Request demo access</h3>
                  <p className="auth-copy">Enter your email to receive signup and token instructions.</p>
                  <label htmlFor="signup-email">Signup email</label>
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
                  {signupMessage ? <div className="hint">{signupMessage}</div> : null}
                </form>
              )}

              {isTokenCollapsed ? (
                <div className="auth-collapsed token-summary">
                  <div className="auth-title-row">
                    <div>
                      <div className="auth-title">Access token</div>
                      <div className="auth-value">{maskedToken}</div>
                    </div>
                    <span className="status-badge">Validated</span>
                  </div>
                  <div className="hint">Token validated for the model provider and live market context.</div>
                  <button type="button" className="link-button" onClick={() => setIsTokenCollapsed(false)}>
                    Edit token
                  </button>
                </div>
              ) : (
                <form className="stack-form token-stack" onSubmit={onValidateToken}>
                  <h3>Validate token</h3>
                  <p className="auth-copy">Paste the access token before starting chat.</p>
                  {tokenError ? <div className="error form-error">Error: {tokenError}</div> : null}
                  <label htmlFor="api-token">Access token</label>
                  <input
                    id="api-token"
                    value={token}
                    onChange={(event) => {
                      setToken(event.target.value)
                      setIsValidated(false)
                      setTokenError(null)
                    }}
                    placeholder="Paste token"
                    disabled={isValidating}
                  />
                  <button type="submit" disabled={!canValidate}>
                    {isValidating ? 'Checking...' : 'Validate token'}
                  </button>
                  <div className="hint">
                    {isValidated ? 'Ready to ask live questions.' : 'Validation unlocks the chat console.'}
                  </div>
                </form>
              )}
            </section>

            <section className="rail-card context-card">
              <div className="card-kicker">/ market coverage /</div>
              <h2>Built for live market explainability</h2>
              <p>
                The radar turns Polymarket fills, wallet movement, and market metadata into concise explanations you
                can drill into during a demo.
              </p>
              <div className="context-list">
                <div>Top moving markets</div>
                <div>Wallet concentration</div>
                <div>Recent fill evidence</div>
              </div>
            </section>

            <section className="rail-card activity-card">
              <button
                type="button"
                className="activity-toggle"
                onClick={() => setIsSqlCollapsed((current) => !current)}
                aria-expanded={!isSqlCollapsed}
              >
                <span>
                  <span className="card-kicker">/ evidence trail /</span>
                  <strong>{sqlStatements.length} context quer{sqlStatements.length === 1 ? 'y' : 'ies'}</strong>
                </span>
                <span>{isSqlCollapsed ? 'Show' : 'Hide'}</span>
              </button>
              <div className="activity-metrics">
                <div>
                  <span>LLM events</span>
                  <strong>{llmTimingEvents.length}</strong>
                </div>
                <div>
                  <span>Latest</span>
                  <strong>{latestTiming ? formatDuration(latestTiming.durationMs) : '-'}</strong>
                </div>
              </div>
              {!isSqlCollapsed ? (
                <div className="activity-log">
                  {sqlStatements.length === 0 && llmTimingEvents.length === 0 ? (
                    <div className="hint">Context and timing details appear here after a response starts.</div>
                  ) : null}
                  {llmTimingEvents.slice(-3).map((timing, index) => (
                    <div key={`${timing.kind}-${timing.durationMs}-${index}`} className="timing-row">
                      <span>{timing.kind === 'attempt' ? `Attempt ${timing.attempt ?? index + 1}` : 'Summary'}</span>
                      <strong>{formatDuration(timing.durationMs)}</strong>
                    </div>
                  ))}
                  {sqlStatements.slice(-2).map((statement, index) => (
                    <pre key={statement.id} className="sql-block">
                      {`Query ${sqlStatements.length - Math.min(sqlStatements.length, 2) + index + 1}\n${statement.statement}`}
                    </pre>
                  ))}
                </div>
              ) : null}
            </section>
          </aside>

          <section className="chat-shell">
            <div className="chat-header-row">
              <div>
                <div className="feature-kicker">/ chat /</div>
                <h2>Market briefing console</h2>
              </div>
              <div className="chat-header-meta">
                {isValidated ? 'Streaming Polymarket signals and evidence' : 'Validate your token to begin'}
              </div>
            </div>

            <main ref={chatPanelRef} className="chat-panel" onScroll={onChatScroll}>
              {!hasMessages ? (
                <div className="empty-state">
                  <div className="empty-kicker">Live market radar</div>
                  <h3>Start with what changed.</h3>
                  <p>
                    Ask for movers, unusual shifts, concentrated wallet activity, or the trade evidence behind a signal.
                  </p>
                  <div className="prompt-grid" aria-label="Demo prompts">
                    {PROMPTS.slice(0, 4).map((prompt) => (
                      <button key={prompt} onClick={() => void sendMessage(prompt)} disabled={isStreaming || !isValidated}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {messages.map((message) => (
                <article key={message.id} className={`message ${message.role}`}>
                  <div className="meta">{message.role === 'user' ? 'You' : 'Signal Radar'}</div>
                  {message.role === 'assistant' && isStreaming && !message.text ? (
                    <div className="thinking-state">Reading live market context...</div>
                  ) : (
                    renderMessageBody(message)
                  )}
                </article>
              ))}

              {hasMessages && (isStreaming || followUps.length > 0) ? (
                <section className="followup-inline" aria-label="Drill deeper follow-up questions">
                  <div className="meta">Drill deeper</div>
                  {isStreaming ? (
                    <div className="followup-status">Preparing drill-down questions...</div>
                  ) : latestAssistantMessage ? (
                    <div className="followup-list">
                      {followUps.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          className="followup-chip"
                          onClick={() => void sendMessage(prompt)}
                          disabled={isStreaming || !isValidated}
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </main>

            <form className="chat-input" onSubmit={onSubmit}>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder={
                  isValidated
                    ? 'Ask what is moving on Polymarket right now...'
                    : 'Validate access first, then ask a market question.'
                }
                disabled={isStreaming || !isValidated}
                rows={2}
              />
              <div className="composer-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={onClearChat}
                    disabled={isStreaming || !hasMessages}
                  >
                  Clear
                </button>
                <button type="submit" disabled={!canSend}>
                  {isStreaming ? 'Streaming...' : 'Send'}
                </button>
              </div>
            </form>
          </section>
        </section>

        {error ? <div className="error">Error: {error}</div> : null}
      </main>
    </div>
  )
}
