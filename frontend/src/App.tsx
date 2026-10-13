import { useCallback, useEffect, useState } from 'react'
import { Header } from '@/components/Header'
import { Sidebar } from '@/components/Sidebar'
import { ChatArea } from '@/components/ChatArea'
import { WorkspaceDialog } from '@/components/WorkspaceDialog'
import { ConversationProvider, useConversations } from '@/contexts/ConversationContext'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { AuthScreen } from '@/components/AuthScreen'
import { api } from '@/api/client'
import type { Workspace } from '@/types'

function Workspace() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspacesLoading, setWorkspacesLoading] = useState(true)
  const [workspaceDialogOpen, setWorkspaceDialogOpen] = useState(false)

  const {
    conversations,
    currentConversation,
    activeConversationId,
    createConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    refreshCurrentConversation,
  } = useConversations()
  const { account, logout } = useAuth()

  const refreshWorkspaces = useCallback(async () => {
    try {
      const list = await api.listWorkspaces()
      setWorkspaces(list)
    } catch {
      // Workspace listing is optional UI state.
    } finally {
      setWorkspacesLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshWorkspaces()
  }, [refreshWorkspaces])

  const handleSend = useCallback(
    async (content: string) => {
      if (!content.trim() || loading) return

      try {
        let conversationId = activeConversationId
        if (!conversationId) {
          const conv = await createConversation(content.slice(0, 60))
          conversationId = conv.id
        }

        // Persist the user turn so the question is visible immediately.
        await api.addMessage(conversationId, 'user', content)
        await refreshCurrentConversation(conversationId)

        setError(null)
        setLoading(true)

        // The backend owns planning, capability and tool selection.
        const objective = await api.createObjective(content)
        const run = await api.runObjective(objective.id)

        const answer =
          run.final_response?.trim() ||
          `Objective ${objective.id} completed: ${run.details?.completed ?? 0}/${run.details?.total ?? 0} tasks finished.`
        await api.addMessage(conversationId, 'assistant', answer)
        await refreshCurrentConversation(conversationId)
        setLoading(false)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to send message')
        setLoading(false)
      }
    },
    [activeConversationId, createConversation, refreshCurrentConversation, loading],
  )

  const handleNewChat = useCallback(async () => {
    await createConversation('New Conversation')
    setError(null)
  }, [createConversation])

  const handleSelectConversation = useCallback(
    async (id: string) => {
      await selectConversation(id)
    },
    [selectConversation],
  )

  const handleDeleteConversation = useCallback(
    async (id: string) => {
      await deleteConversation(id)
    },
    [deleteConversation],
  )

  const handleRenameConversation = useCallback(
    async (id: string, title: string) => {
      await renameConversation(id, title)
    },
    [renameConversation],
  )

  const handleSelectWorkspace = useCallback(async (workspace: Workspace) => {
    try {
      await api.setActiveWorkspace(workspace.path)
      await refreshWorkspaces()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set active workspace')
    }
  }, [refreshWorkspaces])

  const handleDeleteWorkspace = useCallback(
    async (workspaceId: string) => {
      try {
        await api.deleteWorkspace(workspaceId)
        await refreshWorkspaces()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to remove workspace')
      }
    },
    [refreshWorkspaces],
  )

  const messages = currentConversation?.messages || []

  return (
    <div className="flex h-full w-full flex-col bg-eternix-950 min-h-0">
      <Header
        onNewChat={handleNewChat}
        username={account?.username ?? null}
        onLogout={logout}
      />

      <div className="flex-1 flex min-h-0 min-w-0 overflow-hidden">
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          onSelectConversation={handleSelectConversation}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
          onNewChat={handleNewChat}
          workspaces={workspaces}
          onSelectWorkspace={handleSelectWorkspace}
          onDeleteWorkspace={handleDeleteWorkspace}
          onAddWorkspace={() => setWorkspaceDialogOpen(true)}
          workspacesLoading={workspacesLoading}
        />

        <main className="flex-1 flex flex-col min-w-0 min-h-0">
          <ChatArea
            messages={messages}
            loading={loading}
            error={error}
            onSend={handleSend}
          />
        </main>
      </div>

      <WorkspaceDialog
        open={workspaceDialogOpen}
        onClose={() => setWorkspaceDialogOpen(false)}
        onAdded={refreshWorkspaces}
      />
    </div>
  )
}

function AuthenticatedApp() {
  const { status } = useAuth()

  if (status === 'loading' || status !== 'active') {
    return <AuthScreen />
  }

  return (
    <ConversationProvider>
      <Workspace />
    </ConversationProvider>
  )
}

function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  )
}

export default App
