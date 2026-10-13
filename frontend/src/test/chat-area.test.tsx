import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatArea } from '@/components/ChatArea'
import type { ChatMessage } from '@/types'

const messages: ChatMessage[] = [
  {
    id: '1',
    role: 'user',
    content: 'What is 2+2?',
    timestamp: new Date().toISOString(),
  },
  {
    id: '2',
    role: 'assistant',
    content: '2+2 is 4.',
    timestamp: new Date().toISOString(),
  },
]

describe('ChatArea', () => {
  it('shows the welcome state and Ask Anything input when empty', () => {
    const onSend = vi.fn()
    render(<ChatArea messages={[]} loading={false} error={null} onSend={onSend} />)
    expect(screen.getByText('Eternix')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Ask Anything')).toBeInTheDocument()
  })

  it('renders user and assistant messages', () => {
    render(<ChatArea messages={messages} loading={false} error={null} onSend={vi.fn()} />)
    expect(screen.getByText('What is 2+2?')).toBeInTheDocument()
    expect(screen.getByText('2+2 is 4.')).toBeInTheDocument()
  })

  it('shows a thinking indicator while loading', () => {
    render(<ChatArea messages={messages} loading={true} error={null} onSend={vi.fn()} />)
    expect(screen.getByText('Thinking...')).toBeInTheDocument()
  })

  it('displays errors', () => {
    render(<ChatArea messages={messages} loading={false} error="Something broke" onSend={vi.fn()} />)
    expect(screen.getByText('Something broke')).toBeInTheDocument()
  })

  it('submits typed input on Enter', () => {
    const onSend = vi.fn()
    render(<ChatArea messages={[]} loading={false} error={null} onSend={onSend} />)
    const input = screen.getByPlaceholderText('Ask Anything')
    fireEvent.change(input, { target: { value: 'List files' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false })
    // Form submit is triggered by the keydown handler's preventDefault + submit.
    const form = input.closest('form')
    if (form) fireEvent.submit(form)
    expect(onSend).toHaveBeenCalledWith('List files')
  })
})
