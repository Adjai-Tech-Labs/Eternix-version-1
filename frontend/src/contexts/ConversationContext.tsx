import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import { api } from '../api/client'
import type { Conversation, ChatMessage } from '../types'

interface ConversationContextType {
  conversations: Conversation[]
  currentConversation: (Conversation & { messages: ChatMessage[] }) | null
  activeConversationId: string | null
  loading: boolean
  error: string | null
  createConversation: (title?: string) => Promise<Conversation>
  selectConversation: (id: string) => Promise<void>
  deleteConversation: (id: string) => Promise<void>
  renameConversation: (id: string, title: string) => Promise<void>
  refresh: () => Promise<void>
  refreshCurrentConversation: (conversationId?: string) => Promise<void>
}

const ConversationContext = createContext<ConversationContextType | null>(null)

export function useConversations() {
  const context = useContext(ConversationContext)
  if (!context) throw new Error('useConversations must be used within ConversationProvider')
  return context
}

export const ConversationProvider = ({ children }: { children: ReactNode }) => {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversation, setCurrentConversation] = useState<(Conversation & { messages: ChatMessage[] }) | null>(null)
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.listConversations()
      setConversations(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversations')
    }
  }, [])

  const createConversation = useCallback(async (title?: string) => {
    const conv = await api.createConversation(title || 'New Conversation')
    const now = new Date().toISOString()
    const newConv: Conversation = {
      id: conv.id,
      title: conv.title,
      objective_id: conv.objective_id ?? null,
      created_at: now,
      updated_at: now,
      message_count: 0,
    }
    setConversations(prev => [newConv, ...prev])
    setCurrentConversation({ ...newConv, messages: [] })
    setActiveConversationId(newConv.id)
    return newConv
  }, [])

  const selectConversation = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      const conv = await api.getConversation(id)
      setCurrentConversation(conv)
      setActiveConversationId(id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversation')
    } finally {
      setLoading(false)
    }
  }, [])

  const deleteConversation = useCallback(async (id: string) => {
    await api.deleteConversation(id)
    setConversations(prev => prev.filter(c => c.id !== id))
    if (activeConversationId === id) {
      setCurrentConversation(null)
      setActiveConversationId(null)
    }
  }, [activeConversationId])

  const renameConversation = useCallback(async (id: string, title: string) => {
    await api.renameConversation(id, title)
    setConversations(prev => prev.map(c => (c.id === id ? { ...c, title } : c)))
    if (activeConversationId === id) {
      setCurrentConversation(prev => prev ? { ...prev, title } : null)
    }
  }, [activeConversationId])

  const refreshCurrentConversation = useCallback(async (conversationId?: string) => {
    const id = conversationId ?? activeConversationId
    if (id) {
      try {
        const conv = await api.getConversation(id)
        setCurrentConversation(conv)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to refresh conversation')
      }
    }
  }, [activeConversationId])

  const value = {
    conversations,
    currentConversation,
    activeConversationId,
    loading,
    error,
    createConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    refresh,
    refreshCurrentConversation,
  }

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <ConversationContext.Provider value={value}>
      {children}
    </ConversationContext.Provider>
  )
}
