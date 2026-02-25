# AI ChatKit

A local chat app that connects to an agent deployed in [OpenAI Agent Builder](https://platform.openai.com/docs/guides/agent-builder), using OpenAI's recommended [ChatKit](https://platform.openai.com/docs/guides/chatkit) integration.

## How it works

```
Browser (React + ChatKit widget)
        |
        | POST /api/chatkit/session
        v
Express backend  ──────────────────────>  OpenAI ChatKit API
(exchanges API key + workflow ID         returns client_secret
 for a short-lived client secret)
        |
        | client_secret returned to frontend
        v
ChatKit widget opens a session directly with OpenAI
and streams responses from your Agent Builder workflow
```

The backend never exposes your API key to the browser. The frontend only ever holds a short-lived `client_secret`.

## Prerequisites

- Node.js 18+
- An OpenAI API key — [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- An agent workflow built in [Agent Builder](https://platform.openai.com/docs/guides/agent-builder) — you'll need the **workflow ID** (looks like `wf_...`)

## Setup

**1. Clone or copy this project, then create a `.env` file:**

```
OPENAI_API_KEY=sk-proj-...
WORKFLOW_ID=wf_...
```

**2. Install dependencies:**

```bash
make install
```

**3. Start the app:**

```bash
make dev
```

**4. Open your browser:**

```
http://localhost:5173
```

## Project structure

```
├── server/
│   └── index.ts        # Express backend — creates ChatKit sessions
├── src/
│   ├── App.tsx         # App shell with dark header
│   ├── index.css       # Tailwind + CSS theme variables
│   ├── main.tsx        # React entry point
│   └── components/
│       └── Chat.tsx    # ChatKit React component
├── index.html
├── vite.config.ts      # Vite — proxies /api to Express
├── .env                # Your API key and workflow ID (not committed)
└── Makefile
```

## How to build this from scratch

This follows the [recommended ChatKit integration](https://platform.openai.com/docs/guides/chatkit) from OpenAI.

### Step 1 — Create your agent in Agent Builder

Go to [platform.openai.com](https://platform.openai.com) → **Agents** → **Agent Builder**.

Design your workflow on the visual canvas. When done, copy the **workflow ID** from the URL or the deploy panel — it starts with `wf_`.

### Step 2 — Set up the backend

The backend's only job is to call the ChatKit sessions API using your secret API key (which must never reach the browser) and return a short-lived `client_secret` to the frontend.

```ts
// POST /api/chatkit/session
const response = await fetch('https://api.openai.com/v1/chatkit/sessions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'OpenAI-Beta': 'chatkit_beta=v1',
    Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
  },
  body: JSON.stringify({
    workflow: { id: process.env.WORKFLOW_ID },
    user: 'unique-user-id', // use a real user identifier in production
  }),
})
const { client_secret } = await response.json()
```

> **Security note:** The `user` field should be a unique, stable identifier for the authenticated user in your system. In production, authenticate users before issuing a session.

### Step 3 — Install the ChatKit React package

```bash
npm install @openai/chatkit-react
```

Also add the ChatKit script to your `index.html` `<head>`:

```html
<script src="https://cdn.platform.openai.com/deployments/chatkit/chatkit.js" async></script>
```

### Step 4 — Render the ChatKit component

```tsx
import { ChatKit, useChatKit } from '@openai/chatkit-react'

export function Chat() {
  const { control } = useChatKit({
    api: {
      async getClientSecret(existing) {
        if (existing) return existing
        const res = await fetch('/api/chatkit/session', { method: 'POST' })
        const { client_secret } = await res.json()
        return client_secret
      },
    },
  })

  return <ChatKit control={control} />
}
```

### Step 5 — Proxy `/api` to your backend (Vite)

In `vite.config.ts`, proxy API calls so the dev server forwards `/api` requests to Express:

```ts
server: {
  proxy: {
    '/api': { target: 'http://localhost:3001', changeOrigin: true },
  },
}
```

## Customisation

### Greeting and starter prompts

Configure the start screen in `src/components/Chat.tsx`:

```ts
const { control } = useChatKit({
  api: { ... },
  startScreen: {
    greeting: 'How can I help you today?',
    prompts: [
      { title: 'Show me recent alerts' },
      { title: 'What can you do?' },
    ],
  },
})
```

> Note: the greeting is a plain string — newlines are not rendered by the widget. Keep it short, or use `prompts` to surface key actions.

### Theming

CSS variables in `src/index.css` control the colour scheme. See the [ChatKit theming docs](https://platform.openai.com/docs/guides/chatkit-themes) for the full list of supported variables.

### Agent welcome message

The opening message that the agent sends when a chat starts is configured in **Agent Builder** — in the system prompt or a start node in your workflow. It is not controlled by this app.

## Further reading

- [ChatKit docs](https://platform.openai.com/docs/guides/chatkit)
- [ChatKit JS SDK](https://github.com/openai/chatkit-js)
- [ChatKit theming](https://platform.openai.com/docs/guides/chatkit-themes)
- [ChatKit widgets](https://platform.openai.com/docs/guides/chatkit-widgets)
- [Agent Builder](https://platform.openai.com/docs/guides/agent-builder)
- [Starter app repo](https://github.com/openai/openai-chatkit-starter-app)
