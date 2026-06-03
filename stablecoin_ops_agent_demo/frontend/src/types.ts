export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: Role
  text: string
  latestCtxTimeMs?: number | null
}

export interface StreamResult {
  text: string
  latestCtxTimeMs: number | null
  releaseAllowed: boolean | null
  operationalDisposition: string | null
}
