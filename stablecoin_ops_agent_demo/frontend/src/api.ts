import type { StreamResult } from './types'

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
  onToken: (delta: string) => void,
): Promise<StreamResult> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  let releaseAllowed: boolean | null = null
  let operationalDisposition: string | null = null

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
        if (typeof payload.release_allowed === 'boolean') {
          releaseAllowed = payload.release_allowed
        }
        if (typeof payload.operational_disposition === 'string') {
          operationalDisposition = payload.operational_disposition
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
    releaseAllowed,
    operationalDisposition,
  }
}
