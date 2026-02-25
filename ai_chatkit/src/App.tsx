import Chat from './components/Chat'

export default function App() {
  return (
    <div className="flex flex-col h-full bg-[#0f0f10]">
      {/* Header */}
      <header className="flex items-center gap-3 px-6 py-4 border-b border-[#2a2a2e] bg-[#0f0f10]/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-500/20 ring-1 ring-indigo-500/40">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-indigo-400">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/>
            <path d="M12 8v4l3 3"/>
          </svg>
        </div>
        <div>
          <h1 className="text-sm font-semibold text-white leading-tight">AI Assistant</h1>
          <p className="text-xs text-[#888890] leading-tight">Powered by OpenAI</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span className="text-xs text-[#888890]">Online</span>
        </div>
      </header>

      {/* Chat area */}
      <main className="flex-1 flex flex-col min-h-0 p-4 md:p-6">
        <div className="flex-1 flex flex-col min-h-0 max-w-3xl w-full mx-auto">
          <Chat />
        </div>
      </main>
    </div>
  )
}
