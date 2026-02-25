import { ChatKit, useChatKit } from '@openai/chatkit-react'

export default function Chat() {
  const { control } = useChatKit({
    api: {
      async getClientSecret(existing) {
        if (existing) {
          // Reuse existing secret on refresh — or re-fetch if needed
          return existing
        }
        const res = await fetch('/api/chatkit/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
        if (!res.ok) {
          throw new Error('Failed to get session token')
        }
        const { client_secret } = await res.json()
        return client_secret
      },
    },
    startScreen: {
      greeting:
        `Welcome to the Real-Time AML Monitoring Assistant. You can use this chatbot to review and analyze live anti-money laundering (AML) alerts and suspicious transaction activity from your system. Ask me about the most recent suspicious transactions.`,
    },
  })

  return (
    <ChatKit
      control={control}
      className="flex-1 rounded-xl overflow-hidden border border-[#2a2a2e] shadow-2xl shadow-black/40"
    />
  )
}
