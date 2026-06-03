import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'

import { streamChat } from './api'
import type { ChatMessage } from './types'

const PROMPTS = [
  'Show me the freshest high-priority stablecoin payment exceptions.',
  'What happened with invoice inv_7350? Can we release the order?',
  'Customer says they paid invoice inv_7349. What does the latest context say?',
  'Why is invoice inv_7352 blocked even though payment arrived?',
  'Find recent invoices where the payment arrived on the wrong chain.',
  'Find recent invoices where the customer underpaid or overpaid.',
  'Which payment exceptions changed most recently?',
  'Does invoice inv_6323 look underpaid or overpaid right now?',
]

const createId = () =>
  (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`)

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chatPanelRef = useRef<HTMLElement | null>(null)

  const canSend = useMemo(() => input.trim().length > 0 && !isStreaming, [input, isStreaming])

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
      const result = await streamChat(text, (delta) => {
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
      </header>

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
          disabled={isStreaming}
        />
        <button type="submit" disabled={!canSend}>
          {isStreaming ? 'Streaming...' : 'Send'}
        </button>
      </form>

      {error ? <div className="error">Error: {error}</div> : null}
    </div>
  )
}
