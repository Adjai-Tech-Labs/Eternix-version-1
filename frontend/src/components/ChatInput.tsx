import { useState, useRef, useEffect } from 'react'
import { cn } from '@/utils/helpers'
import { Button } from '@/components/ui/Button'
import { Send, X, Paperclip, Square, Loader2 } from 'lucide-react'

interface Attachment {
  id: string
  name: string
  type: string
  size: number
}

interface ChatInputProps {
  onSubmit: (content: string, attachments?: Attachment[]) => void
  disabled?: boolean
  placeholder?: string
  onStop?: () => void
  isRunning?: boolean
}

export const ChatInput = ({
  onSubmit,
  disabled,
  placeholder = 'Ask Anything...',
  onStop,
  isRunning,
}: ChatInputProps) => {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [value])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if ((!trimmed && attachments.length === 0) || disabled) return

    onSubmit(trimmed, attachments.length > 0 ? attachments : undefined)
    setValue('')
    setAttachments([])
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    const newAttachments: Attachment[] = files.map(file => ({
      id: `${file.name}-${file.size}-${Date.now()}`,
      name: file.name,
      type: file.type,
      size: file.size,
    }))
    setAttachments(prev => [...prev, ...newAttachments])
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const removeAttachment = (id: string) => {
    setAttachments(prev => prev.filter(a => a.id !== id))
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const getFileIcon = (type: string) => {
    if (type.startsWith('image/')) return <Image className="w-4 h-4" />
    if (type.startsWith('text/') || type === 'application/json') return <FileText className="w-4 h-4" />
    if (type.startsWith('application/')) return <Square className="w-4 h-4" />
    return <FileText className="w-4 h-4" />
  }

  return (
    <form onSubmit={handleSubmit} className="w-full px-4 py-3">
      {attachments.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-2 px-1">
          <Paperclip className="w-4 h-4 text-eternix-500 flex-shrink-0" />
          {attachments.map(attachment => (
            <div key={attachment.id} className="attachment-chip flex items-center gap-2">
              {getFileIcon(attachment.type)}
              <span className="truncate max-w-[150px]">{attachment.name}</span>
              <span className="text-xs text-eternix-500">{formatFileSize(attachment.size)}</span>
              <button
                type="button"
                onClick={() => removeAttachment(attachment.id)}
                className="attachment-chip-remove"
                aria-label={`Remove ${attachment.name}`}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1 relative min-w-0">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            multiple
            className="absolute inset-0 opacity-0 cursor-pointer"
            aria-label="Attach files"
            accept=".txt,.md,.js,.ts,.jsx,.tsx,.py,.json,.csv,.pdf,.png,.jpg,.jpeg,.gif,.webp"
          />
          <label
            htmlFor="file-attach"
            className="absolute left-3 top-1/2 -translate-y-1/2 p-2 rounded-lg text-eternix-500 hover:text-eternix-300 hover:bg-eternix-800 transition-colors cursor-pointer"
            aria-label="Attach files"
          >
            <Paperclip className="w-5 h-5" />
          </label>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled || isRunning}
            rows={1}
            className={cn(
              'w-full px-4 py-3 pl-12 pr-12 bg-eternix-900 rounded-xl resize-none transition-all duration-200',
              'text-eternix-100 placeholder-eternix-500',
              'focus:outline-none focus:ring-2 focus:ring-eternix-purple-500 focus:border-transparent',
              disabled || isRunning ? 'opacity-50 cursor-not-allowed' : 'border-eternix-700 border',
              'min-h-[52px]',
            )}
            style={{ maxHeight: '200px' }}
            aria-label="Ask Anything"
          />
        </div>

        {isRunning && onStop ? (
          <Button
            type="button"
            variant="danger"
            size="lg"
            onClick={onStop}
            aria-label="Stop generation"
            className="h-12 w-12 p-0 flex-shrink-0 min-w-[48px]"
          >
            <Square className="w-5 h-5" />
          </Button>
        ) : (
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={disabled || isRunning || (!value.trim() && attachments.length === 0)}
            aria-label="Send message"
            className="h-12 w-12 p-0 flex-shrink-0 min-w-[48px]"
          >
            {isRunning ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </Button>
        )}
      </div>

      <div className="flex items-center gap-3 mt-2 px-1 text-xs text-eternix-500">
        <span>Enter to send</span>
        <span>•</span>
        <span>Shift+Enter for a new line</span>
        <span>•</span>
        <span>Attach files with the paperclip</span>
      </div>
    </form>
  )
}
