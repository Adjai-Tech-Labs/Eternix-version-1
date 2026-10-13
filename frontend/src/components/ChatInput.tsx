import { useState, useRef, useEffect } from 'react'
import { cn } from '@/utils/helpers'
import { Button } from '@/components/ui/Button'
import { Send } from 'lucide-react'

interface ChatInputProps {
  onSubmit: (content: string) => void
  disabled?: boolean
  placeholder?: string
}

export const ChatInput = ({
  onSubmit,
  disabled,
  placeholder = 'Ask Anything',
}: ChatInputProps) => {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [value])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return

    onSubmit(trimmed)
    setValue('')
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

  return (
    <form onSubmit={handleSubmit} className="w-full px-4 py-3">
      <div className="flex items-end gap-2">
        <div className="flex-1 relative min-w-0">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className={cn(
              'w-full px-4 py-3 pr-4 bg-eternix-900 rounded-xl resize-none transition-all duration-200',
              'text-eternix-100 placeholder-eternix-500',
              'focus:outline-none focus:ring-2 focus:ring-eternix-500 focus:border-transparent',
              disabled ? 'opacity-50 cursor-not-allowed' : 'border-eternix-700 border',
              'min-h-[52px]',
            )}
            style={{ maxHeight: '200px' }}
            aria-label="Ask Anything"
          />
        </div>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={disabled || !value.trim()}
          aria-label="Send message"
          className="h-12 w-12 p-0 flex-shrink-0 min-w-[48px]"
        >
          <Send className="w-5 h-5" />
        </Button>
      </div>

      <div className="flex items-center gap-3 mt-2 px-1 text-xs text-eternix-500">
        <span>Enter to send</span>
        <span>•</span>
        <span>Shift+Enter for a new line</span>
      </div>
    </form>
  )
}
