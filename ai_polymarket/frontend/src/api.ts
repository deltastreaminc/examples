import type { StreamResult } from './types'

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
  const response = await fetch('/api/token/validate', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>
    const detail = typeof payload.detail === 'string' ? payload.detail : `status ${response.status}`
    throw new Error(`Token validation failed: ${detail}`)
  }
}

function parseEventBlock(block: string): { event: string; data: unknown } | null {
  const lines = block.split('\n')
  let event = 'message'
  const dataLines: string[] = []

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (!dataLines.length) {
    return null
  }

  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

export async function streamChat(
  message: string,
  token: string,
  onToken: (delta: string) => void,
): Promise<StreamResult> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
  })

  if (!response.ok || !response.body) {
    throw new Error(`Request failed with status ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  let buffer = ''
  let finalText = ''
  let latestCtxTimeMs: number | null = null
  let questionMode: string | null = null
  let queriedViews: string[] = []

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })

    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''

    for (const block of blocks) {
      const parsed = parseEventBlock(block)
      if (!parsed || typeof parsed.data !== 'object' || parsed.data === null) {
        continue
      }

      const payload = parsed.data as Record<string, unknown>

      if (parsed.event === 'token') {
        const text = payload.text
        if (typeof text === 'string') {
          onToken(text)
        }
      }

      if (parsed.event === 'context_meta') {
        const ctxValue = payload.latest_ctx_time_ms
        if (typeof ctxValue === 'number') {
          latestCtxTimeMs = ctxValue
        }
        if (typeof payload.question_mode === 'string') {
          questionMode = payload.question_mode
        }
        if (Array.isArray(payload.queried_views)) {
          queriedViews = payload.queried_views.filter((value): value is string => typeof value === 'string')
        }
      }

      if (parsed.event === 'final') {
        const text = payload.text
        if (typeof text === 'string') {
          finalText = text
        }
        const ctxValue = payload.latest_ctx_time_ms
        if (typeof ctxValue === 'number') {
          latestCtxTimeMs = ctxValue
        }
        if (typeof payload.question_mode === 'string') {
          questionMode = payload.question_mode
        }
        if (Array.isArray(payload.queried_views)) {
          queriedViews = payload.queried_views.filter((value): value is string => typeof value === 'string')
        }
      }

      if (parsed.event === 'error') {
        const messageValue = payload.message
        if (typeof messageValue === 'string') {
          throw new Error(messageValue)
        }
        throw new Error('Unknown streaming error')
      }
    }
  }

  return {
    text: finalText,
    latestCtxTimeMs,
    questionMode,
    queriedViews,
  }
}
