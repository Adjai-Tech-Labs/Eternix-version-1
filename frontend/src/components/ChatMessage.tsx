import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import remarkGfm from 'remark-gfm'
import { Copy, Terminal, Check } from 'lucide-react'
import { formatRelativeTime } from '@/utils/helpers'
import type { ChatMessage } from '@/types'

interface ChatMessageProps {
  message: ChatMessage
}

export const ChatMessageComponent = ({ message }: ChatMessageProps) => {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end animate-slide-up">
        <div className="max-w-[85%]">
          <div className="bg-eternix-700 text-eternix-50 rounded-2xl rounded-tr-sm px-4 py-3">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {message.content}
            </ReactMarkdown>
          </div>
          <div className="flex justify-end mt-1">
            <span className="text-xs text-eternix-500">
              {formatRelativeTime(message.timestamp)}
            </span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex animate-slide-up" data-message-id={message.id}>
      <div className="w-8 h-8 flex-shrink-0 mt-1">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-eternix-500 to-eternix-700 flex items-center justify-center">
          <Terminal className="w-4 h-4 text-white" />
        </div>
      </div>
      <div className="flex-1 min-w-0 ml-3">
        <div className="bg-eternix-800/50 border border-eternix-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {message.content}
          </ReactMarkdown>
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-xs text-eternix-500">
            {formatRelativeTime(message.timestamp)}
          </span>
          <CopyButton content={message.content} />
        </div>
      </div>
    </div>
  )
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable; ignore.
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="text-eternix-500 hover:text-eternix-300 transition-colors"
      aria-label="Copy message"
      title="Copy"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  )
}
