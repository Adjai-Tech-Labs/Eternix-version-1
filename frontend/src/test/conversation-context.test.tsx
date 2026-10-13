import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { ConversationProvider, useConversations } from '@/contexts/ConversationContext'
import { api } from '@/api/client'
import type { Conversation } from '@/types'

vi.mock('@/api/client', () => ({
  api: {
    listConversations: vi.fn(),
    createConversation: vi.fn(),
    getConversation: vi.fn(),
    deleteConversation: vi.fn(),
    renameConversation: vi.fn(),
  },
}))

const conversation: Conversation = {
  id: 'c1',
  title: 'Test chat',
  objective_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  message_count: 1,
}

function Probe() {
  const {
    conversations,
    currentConversation,
    activeConversationId,
    createConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
  } = useConversations()
  return (
    <div>
      <span data-testid="count">{conversations.length}</span>
      <span data-testid="active">{activeConversationId ?? 'none'}</span>
      <span data-testid="messages">
        {currentConversation ? currentConversation.messages.length : -1}
      </span>
      <button onClick={() => createConversation('New chat')}>create</button>
      <button onClick={() => selectConversation('c1')}>select</button>
      <button onClick={() => deleteConversation('c1')}>delete</button>
      <button onClick={() => renameConversation('c1', 'Renamed')}>rename</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <ConversationProvider>
      <Probe />
    </ConversationProvider>,
  )
}

describe('ConversationContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads the conversation list on mount', async () => {
    vi.mocked(api.listConversations).mockResolvedValue([conversation])
    renderProvider()
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('1')
    })
  })

  it('creates a conversation and makes it active', async () => {
    vi.mocked(api.listConversations).mockResolvedValue([])
    vi.mocked(api.createConversation).mockResolvedValue({ id: 'c2', title: 'New chat' })
    renderProvider()
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('0')
    })
    await act(async () => {
      fireEvent.click(screen.getByText('create'))
    })
    await waitFor(() => {
      expect(screen.getByTestId('active')).toHaveTextContent('c2')
      expect(screen.getByTestId('messages')).toHaveTextContent('0')
    })
  })

  it('selects a conversation and loads its messages', async () => {
    vi.mocked(api.listConversations).mockResolvedValue([conversation])
    vi.mocked(api.getConversation).mockResolvedValue({
      ...conversation,
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'hello',
          timestamp: new Date().toISOString(),
        },
      ],
    })
    renderProvider()
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('1')
    })
    await act(async () => {
      fireEvent.click(screen.getByText('select'))
    })
    await waitFor(() => {
      expect(screen.getByTestId('active')).toHaveTextContent('c1')
      expect(screen.getByTestId('messages')).toHaveTextContent('1')
    })
  })

  it('deletes a conversation', async () => {
    vi.mocked(api.listConversations).mockResolvedValue([conversation])
    vi.mocked(api.deleteConversation).mockResolvedValue(undefined)
    renderProvider()
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('1')
    })
    await act(async () => {
      fireEvent.click(screen.getByText('delete'))
    })
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('0')
    })
  })

  it('renames a conversation', async () => {
    vi.mocked(api.listConversations).mockResolvedValue([conversation])
    vi.mocked(api.renameConversation).mockResolvedValue({ id: 'c1', title: 'Renamed' })
    renderProvider()
    await waitFor(() => {
      expect(screen.getByTestId('count')).toHaveTextContent('1')
    })
    await act(async () => {
      fireEvent.click(screen.getByText('rename'))
    })
    expect(api.renameConversation).toHaveBeenCalledWith('c1', 'Renamed')
  })
})
