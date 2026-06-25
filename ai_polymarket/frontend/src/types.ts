export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: Role
  text: string
  latestCtxTimeMs?: number | null
  questionMode?: string | null
  queriedViews?: string[]
}

export interface StreamResult {
  text: string
  latestCtxTimeMs: number | null
  questionMode: string | null
  queriedViews: string[]
}
