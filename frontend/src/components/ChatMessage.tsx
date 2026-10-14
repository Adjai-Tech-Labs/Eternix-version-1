import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import remarkGfm from 'remark-gfm'
import { Copy, Terminal, Check, FileText, Image, Code2 } from 'lucide-react'
import { formatRelativeTime } from '@/utils/helpers'
import type { ChatMessage } from '@/types'

interface ChatMessageProps {
  message: ChatMessage
}

const markdownComponents = {
  code: ({ node, children, ...props }: any) => {
    const className = node.properties?.className || ''
    const language = className.replace('language-', '') || 'text'
    return (
      <div className="relative group my-2">
        <div className="flex items-center justify-between px-3 py-2 bg-eternix-950 border-b border-eternix-700">
          <span className="text-xs text-eternix-500 font-mono">{language}</span>
          <CopyButton content={String(children)} />
        </div>
        <pre className="code-block p-4 overflow-x-auto"><code className={`language-${language} text-eternix-100`}>{String(children)}</code></pre>
      </div>
    )
  },
  pre: ({ children }: any) => (
    <div className="relative group my-2">
      <pre className="code-block p-4 overflow-x-auto"><code className="text-eternix-100">{children}</code></pre>
    </div>
  ),
  a: ({ href, children, ...props }: any) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-eternix-lightBlue-400 hover:text-eternix-lightBlue-300 underline hover:no-underline transition-colors"
      {...props}
    >
      {children}
    </a>
  ),
  img: ({ src, alt, ...props }: any) => (
    <div className="my-4">
      <img
        src={src}
        alt={alt || 'Image'}
        className="max-w-full h-auto rounded-lg border border-eternix-700"
        loading="lazy"
        {...props}
      />
      {alt && <p className="text-xs text-eternix-500 mt-1 text-center">{alt}</p>}
    </div>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-4 border-eternix-purple-500 pl-4 my-4 italic text-eternix-300">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-eternix-700 my-6" />,
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-1 my-2">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-1 my-2">{children}</ol>,
  li: ({ children }: any) => <li className="ml-4">{children}</li>,
  p: ({ children }: any) => <p className="my-2 leading-relaxed">{children}</p>,
  h1: ({ children }: any) => <h1 className="text-2xl font-bold mt-6 mb-3 text-eternix-100">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-xl font-bold mt-5 mb-2 text-eternix-100">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-lg font-bold mt-4 mb-2 text-eternix-100">{children}</h3>,
  strong: ({ children }: any) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }: any) => <em className="italic">{children}</em>,
  inlineCode: ({ children }: any) => (
    <code className="inline-code">{children}</code>
  ),
}

export const ChatMessageComponent = ({ message }: ChatMessageProps) => {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end animate-slide-up">
        <div className="max-w-[85%]">
          <div className="bg-eternix-purple-600/30 text-eternix-100 rounded-2xl rounded-tr-sm px-4 py-3 border border-eternix-purple-500/20">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={markdownComponents}>
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
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-eternix-purple-500 to-eternix-purple-700 flex items-center justify-center">
          <Terminal className="w-4 h-4 text-white" />
        </div>
      </div>
      <div className="flex-1 min-w-0 ml-3">
        <div className="bg-eternix-900/50 border border-eternix-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={markdownComponents}>
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
      className="text-eternix-500 hover:text-eternix-300 transition-colors p-1 rounded"
      aria-label="Copy message"
      title="Copy"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  )
}
