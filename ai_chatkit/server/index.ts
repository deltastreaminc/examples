import express from 'express'
import cors from 'cors'
import dotenv from 'dotenv'

dotenv.config()

const app = express()
app.use(cors())
app.use(express.json())

const OPENAI_API_KEY = process.env.OPENAI_API_KEY!
const WORKFLOW_ID = process.env.WORKFLOW_ID!

app.post('/api/chatkit/session', async (_req, res) => {
  try {
    const response = await fetch('https://api.openai.com/v1/chatkit/sessions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'OpenAI-Beta': 'chatkit_beta=v1',
        Authorization: `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        workflow: { id: WORKFLOW_ID },
        user: `local-user-${Date.now()}`,
      }),
    })

    if (!response.ok) {
      const error = await response.text()
      console.error('OpenAI error:', error)
      res.status(response.status).json({ error })
      return
    }

    const data = await response.json() as { client_secret: string }
    res.json({ client_secret: data.client_secret })
  } catch (err) {
    console.error('Session error:', err)
    res.status(500).json({ error: 'Failed to create session' })
  }
})

const PORT = 3001
app.listen(PORT, () => {
  console.log(`Backend running on http://localhost:${PORT}`)
})
