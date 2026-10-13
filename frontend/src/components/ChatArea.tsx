import { useState, useRef, useEffect, useCallback } from 'react'
import { cn } from '@/utils/helpers'
import { ChatMessageComponent } from '@/components/ChatMessage'
import { ChatInput } from '@/components/ChatInput'
import { Terminal, Loader2, AlertCircle, ChevronDown, Sparkles } from 'lucide-react'
import type { ChatMessage as ChatMessageType } from '@/types'

interface ChatAreaProps {
  messages: ChatMessageType[]
  loading: boolean
  error: string | null
  onSend: (content: string) => void
  emptyMessage?: string
  className?: string
}

export const ChatArea = ({
  messages,
  loading,
  error,
  onSend,
  className,
}: ChatAreaProps) => {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const [userScrolled, setUserScrolled] = useState(false)

  useEffect(() => {
    if (!userScrolled || messages.length === 0) {
      scrollToBottom()
    }
  }, [messages, loading])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const handleScroll = () => {
    if (scrollAreaRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollAreaRef.current
      setUserScrolled(scrollHeight - scrollTop - clientHeight > 100)
    }
  }

  const handleSend = useCallback(
    (content: string) => {
      setUserScrolled(false)
      onSend(content)
    },
    [onSend],
  )

  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center min-h-0">
        <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-eternix-500 to-eternix-700 flex items-center justify-center mb-6 animate-fade-in">
          <Terminal className="w-10 h-10 text-white" />
        </div>
        <h1 className="text-3xl font-bold text-eternix-100 mb-2">Eternix</h1>
        <p className="text-eternix-400 mb-8 max-w-md">
          Ask anything. The agent plans, picks its own tools, and answers.
        </p>
        <div className="w-full max-w-xl space-y-3">
          <div className="flex items-center gap-3 p-3 bg-eternix-900/50 rounded-lg text-left">
            <Sparkles className="w-5 h-5 text-eternix-500 flex-shrink-0" />
            <p className="text-sm text-eternix-400">
              Describe a task in plain language — the agent handles the rest.
            </p>
          </div>
          <div className="flex items-center gap-3 p-3 bg-eternix-900/50 rounded-lg text-left">
            <Sparkles className="w-5 h-5 text-eternix-500 flex-shrink-0" />
            <p className="text-sm text-eternix-400">
              Register workspace folders in the sidebar to give the agent access to your files.
            </p>
          </div>
        </div>
        <div className="w-full max-w-xl mt-8">
          <ChatInput onSubmit={handleSend} disabled={loading} />
        </div>
      </div>
    )
  }

  return (
    <div className={cn('flex-1 flex flex-col min-h-0 min-w-0', className)}>
      <div
        ref={scrollAreaRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto"
      >
        <div className="flex flex-col gap-4 p-4 pb-0">
          {messages.map((message, index) => (
            <ChatMessageComponent key={`${message.id}-${index}`} message={message} />
          ))}

          {loading && (
            <div className="flex items-start gap-3 animate-fade-in">
              <div className="w-8 h-8 flex-shrink-0 mt-1">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-eternix-500 to-eternix-700 flex items-center justify-center">
                  <Loader2 className="w-4 h-4 text-white animate-spin" />
                </div>
              </div>
              <div className="flex-1 min-w-0 ml-3">
                <div className="bg-eternix-800/50 border border-eternix-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-eternix-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-eternix-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-eternix-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                    <span className="text-eternix-300">Thinking...</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-3 animate-slide-up">
              <div className="w-8 h-8 flex-shrink-0 mt-1">
                <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
                  <AlertCircle className="w-4 h-4 text-red-400" />
                </div>
              </div>
              <div className="flex-1 min-w-0 ml-3">
                <div className="border border-red-500/30 bg-red-500/5 rounded-xl p-4">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="font-medium text-red-300">Error</p>
                      <p className="text-sm text-eternix-400 mt-1">{error}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {userScrolled && (
        <div className="fixed bottom-24 right-4 z-10 animate-fade-in">
          <button
            onClick={() => {
              setUserScrolled(false)
              scrollToBottom()
            }}
            className="p-2 rounded-lg bg-eternix-700 text-eternix-100 shadow-xl hover:bg-eternix-600 transition-colors"
            aria-label="Scroll to bottom"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="border-t border-eternix-800 bg-eternix-950/50 backdrop-blur-sm">
        <ChatInput onSubmit={handleSend} disabled={loading} />
      </div>
    </div>
  )
}
