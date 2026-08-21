import type { DocSearchQuery, LlmTimingEvent, SqlStatement, StreamResult } from './types'

// Routing model for this deployment:
// - Token validation and signup are served by the demo platform at the host root
//   (/api/*) — NOT by this container. They use root-absolute paths.
// - The chat endpoint is served by THIS container, which may be mounted under a
//   path prefix (e.g. /polymarket/). The prefix is injected at runtime by the
//   backend as window.__APP_BASE__ (always ends with '/'; "/" when at root), so a
//   single build works at any mount path without a build-time base.
const appBase = (): string => {
  const base = (globalThis as unknown as { __APP_BASE__?: string }).__APP_BASE__
  return typeof base === 'string' && base ? base : '/'
}
const containerApiUrl = (path: string): string => `${appBase()}${path.replace(/^\//, '')}`

export class PartialStreamError extends Error {
  partialText: string

  constructor(message: string, partialText: string) {
    super(message)
    this.name = 'PartialStreamError'
    this.partialText = partialText
  }
}

export async function signup(email: string): Promise<string> {
  const response = await fetch('/api/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `status ${response.status}`
    throw new Error(`Signup failed: ${detail}`)
  }
  if (typeof payload.message === 'string' && payload.message.trim()) {
    return payload.message
  }
  return 'Signup succeeded. Check your email to confirm your address.'
}

export async function validateToken(token: string): Promise<void> {
  // Served by the demo platform at the host root (/api/token/validate).
  const response = await fetch('/api/token/validate', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok || payload.valid === false) {
    const detail =
      typeof payload.detail === 'string'
        ? payload.detail
        : typeof payload.message === 'string'
          ? payload.message
          : `status ${response.status}`
    throw new Error(`Token validation failed: ${detail}`)
  }
}

export async function streamChat(
  message: string,
  token: string,
  onToken: (delta: string) => void,
  onSql: (statement: SqlStatement) => void,
  onDocSearch: (query: DocSearchQuery) => void,
  onLlmTiming: (timing: LlmTimingEvent) => void,
  onReset?: () => void,
  conversationId?: string,
): Promise<StreamResult> {
  let finalText = ''
  let streamedText = ''
  let followUps: string[] = []

  const isRenderableFollowUp = (question: string) => question.match(/\b[\w'-]+\b/g)?.length ?? 0 >= 2

  // Apply a single {event, data} item. Returns the message of a terminal error
  // event (caller should stop and surface a PartialStreamError), or null.
  const applyEvent = (event: string, data: Record<string, unknown>): string | null => {
    if (event === 'reset') {
      streamedText = ''
      finalText = ''
      onReset?.()
    } else if (event === 'token') {
      const text = data.text
      if (typeof text === 'string') {
        streamedText += text
        onToken(text)
      }
    } else if (event === 'sql') {
      const statement = data.statement
      if (typeof statement === 'string') {
        onSql({ id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, statement })
      }
    } else if (event === 'doc_search') {
      const query = data.query
      if (typeof query === 'string') {
        onDocSearch({ id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, query })
      }
    } else if (event === 'llm_timing') {
      const kind = data.kind
      const durationMs = data.duration_ms
      if ((kind === 'attempt' || kind === 'summary') && typeof durationMs === 'number') {
        onLlmTiming({
          kind,
          durationMs,
          attempt: typeof data.attempt === 'number' ? data.attempt : undefined,
          attempts: typeof data.attempts === 'number' ? data.attempts : undefined,
          accepted: typeof data.accepted === 'boolean' ? data.accepted : undefined,
          hadDataQuery: typeof data.had_data_query === 'boolean' ? data.had_data_query : undefined,
          outputChars: typeof data.output_chars === 'number' ? data.output_chars : undefined,
        })
      }
    } else if (event === 'final') {
      if (typeof data.text === 'string') {
        finalText = data.text
      }
    } else if (event === 'follow_ups') {
      const questions = data.questions
      if (Array.isArray(questions)) {
        const seen = new Set<string>()
        followUps = questions
          .filter((question): question is string => typeof question === 'string')
          .map((question) => question.trim())
          .filter((question) => question.length > 0)
          .filter((question) => isRenderableFollowUp(question))
          .filter((question) => {
            const key = question.toLowerCase()
            if (seen.has(key)) {
              return false
            }
            seen.add(key)
            return true
          })
          .slice(0, 3)
      }
    } else if (event === 'error') {
      return typeof data.message === 'string' ? data.message : 'Unknown streaming error'
    }
    return null
  }

  // 1) Start the chat as a background job.
  const startResponse = await fetch(containerApiUrl('/api/chat/start'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
  if (!startResponse.ok) {
    const payload = (await startResponse.json().catch(() => ({}))) as Record<string, unknown>
    const detail = typeof payload.detail === 'string' ? payload.detail : `status ${startResponse.status}`
    throw new Error(`Chat request failed: ${detail}`)
  }
  const startPayload = (await startResponse.json()) as { job_id?: string }
  const jobId = startPayload.job_id
  if (!jobId) {
    throw new Error('Chat request failed: missing job id')
  }

  // 2) Poll for buffered events in short requests until the job finishes.
  let cursor = 0
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

  while (true) {
    const pollResponse = await fetch(
      containerApiUrl(`/api/chat/poll/${jobId}?cursor=${cursor}`),
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!pollResponse.ok) {
      const message = `Chat polling failed: status ${pollResponse.status}`
      const partial = finalText || streamedText
      if (partial) {
        throw new PartialStreamError(message, partial)
      }
      throw new Error(message)
    }

    const data = (await pollResponse.json()) as {
      events?: Array<{ event?: string; data?: Record<string, unknown> }>
      cursor?: number
      status?: string
    }
    cursor = typeof data.cursor === 'number' ? data.cursor : cursor

    for (const item of data.events ?? []) {
      if (!item || typeof item.event !== 'string') {
        continue
      }
      const errorMessage = applyEvent(item.event, item.data ?? {})
      if (errorMessage !== null) {
        throw new PartialStreamError(errorMessage, finalText || streamedText)
      }
    }

    if (data.status === 'done' || data.status === 'error') {
      break
    }
    await sleep(700)
  }

  return {
    text: finalText || streamedText,
    followUps,
  }
}
