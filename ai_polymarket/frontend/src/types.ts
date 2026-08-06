export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: Role
  text: string
}

export interface StreamResult {
  text: string
  followUps: string[]
}

export interface SqlStatement {
  id: string
  statement: string
}

export interface DocSearchQuery {
  id: string
  query: string
}

export interface LlmTimingEvent {
  kind: 'attempt' | 'summary'
  attempt?: number
  attempts?: number
  durationMs: number
  accepted?: boolean
  hadDataQuery?: boolean
  outputChars?: number
}
