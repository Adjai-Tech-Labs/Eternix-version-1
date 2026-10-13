import { useState } from 'react'
import { cn, truncate } from '@/utils/helpers'
import { Badge } from '@/components/ui/Badge'
import { ScrollArea } from '@/components/ui/ScrollArea'
import { Separator } from '@/components/ui/Separator'
import {
  MessageSquare,
  FolderOpen,
  FolderPlus,
  Trash2,
  CheckCircle,
  Circle,
  TerminalSquare,
  Loader2,
} from 'lucide-react'
import type { Conversation, Workspace } from '@/types'

interface SidebarProps {
  conversations: Conversation[]
  activeConversationId: string | null
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => void
  onRenameConversation: (id: string, title: string) => void
  onNewChat: () => void
  workspaces: Workspace[]
  onSelectWorkspace: (workspace: Workspace) => void
  onDeleteWorkspace: (workspaceId: string) => void
  onAddWorkspace: () => void
  workspacesLoading?: boolean
  className?: string
}

export const Sidebar = ({
  conversations,
  activeConversationId,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
  onNewChat,
  workspaces,
  onSelectWorkspace,
  onDeleteWorkspace,
  onAddWorkspace,
  workspacesLoading,
  className,
}: SidebarProps) => {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const startRename = (conv: Conversation) => {
    setEditingId(conv.id)
    setEditTitle(conv.title)
  }

  const confirmRename = (id: string) => {
    const trimmed = editTitle.trim()
    if (trimmed) {
      onRenameConversation(id, trimmed)
    }
    setEditingId(null)
  }

  return (
    <div
      className={cn(
        'w-72 h-full bg-eternix-900/80 backdrop-blur-md border-r border-eternix-800 flex flex-col flex-shrink-0',
        className,
      )}
    >
      <div className="flex h-16 items-center gap-3 px-4 border-b border-eternix-800">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-eternix-500 to-eternix-700 flex items-center justify-center">
          <TerminalSquare className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="font-semibold text-eternix-100 text-sm">Eternix</h1>
          <p className="text-xs text-eternix-500">Agent Workspace</p>
        </div>
      </div>

      <div className="px-3 py-3">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-eternix-600/20 text-eternix-100 hover:bg-eternix-600/30 transition-colors"
        >
          <MessageSquare className="w-5 h-5" />
          <span>New Chat</span>
        </button>
      </div>

      <ScrollArea className="flex-1 min-h-0 px-3 pb-3">
        <div className="flex items-center justify-between px-2 py-2">
          <span className="text-xs font-semibold text-eternix-500 uppercase tracking-wider">
            Previous Chats
          </span>
        </div>
        <div className="space-y-1">
          {conversations.length === 0 ? (
            <p className="text-xs text-eternix-500 py-2 px-2">No conversations yet</p>
          ) : (
            conversations.map(conv => (
              <div
                key={conv.id}
                className={cn(
                  'group flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors',
                  activeConversationId === conv.id
                    ? 'bg-eternix-700/50 text-eternix-100'
                    : 'text-eternix-400 hover:bg-eternix-800/50 hover:text-eternix-100',
                )}
                onClick={() => onSelectConversation(conv.id)}
                role="button"
                tabIndex={0}
                onKeyDown={e => {
                  if (e.key === 'Enter') onSelectConversation(conv.id)
                }}
              >
                {editingId === conv.id ? (
                  <>
                    <input
                      type="text"
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') confirmRename(conv.id)
                        if (e.key === 'Escape') setEditingId(null)
                      }}
                      className="flex-1 bg-eternix-800 text-eternix-100 text-sm px-2 py-1 rounded"
                      autoFocus
                    />
                    <button
                      onClick={e => {
                        e.stopPropagation()
                        confirmRename(conv.id)
                      }}
                      className="p-0.5 rounded text-eternix-300 hover:text-eternix-100"
                      aria-label="Rename conversation"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <>
                    <Circle className="w-2 h-2 fill-current text-eternix-500 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{conv.title}</p>
                      <p className="text-xs text-eternix-500 truncate">
                        {conv.message_count} message{conv.message_count === 1 ? '' : 's'}
                      </p>
                    </div>
                    <div
                      className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 transition-opacity"
                      onClick={e => {
                        e.stopPropagation()
                        startRename(conv)
                      }}
                    >
                      <button
                        onClick={e => {
                          e.stopPropagation()
                          onDeleteConversation(conv.id)
                        }}
                        className="p-1 rounded text-eternix-400 hover:text-red-400 hover:bg-eternix-800/50"
                        aria-label="Delete conversation"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))
          )}
        </div>

        <Separator className="my-3" />

        <div className="flex items-center justify-between px-2 py-2">
          <span className="text-xs font-semibold text-eternix-500 uppercase tracking-wider">
            Workspaces
          </span>
          <button
            onClick={onAddWorkspace}
            className="p-1 rounded-lg text-eternix-400 hover:bg-eternix-800/50 hover:text-eternix-100 transition-colors"
            aria-label="Add workspace folder"
            title="Add workspace folder"
          >
            <FolderPlus className="w-4 h-4" />
          </button>
        </div>
        {workspacesLoading ? (
          <div className="flex items-center gap-2 px-2 py-2 text-xs text-eternix-500">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading workspaces...
          </div>
        ) : workspaces.length === 0 ? (
          <p className="text-xs text-eternix-500 py-2 px-2">
            No workspaces. Add a folder from your PC.
          </p>
        ) : (
          <div className="space-y-1">
            {workspaces.map(ws => (
              <div
                key={ws.id}
                className={cn(
                  'group flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors',
                  ws.active
                    ? 'bg-eternix-700/50 text-eternix-100'
                    : 'text-eternix-400 hover:bg-eternix-800/50 hover:text-eternix-100',
                )}
                onClick={() => onSelectWorkspace(ws)}
                role="button"
                tabIndex={0}
                onKeyDown={e => {
                  if (e.key === 'Enter') onSelectWorkspace(ws)
                }}
                title={ws.path}
              >
                <FolderOpen
                  className={cn(
                    'w-4 h-4 flex-shrink-0',
                    ws.active ? 'text-eternix-400' : 'text-eternix-500',
                  )}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{ws.name}</p>
                  <p className="text-xs text-eternix-500 truncate">{truncate(ws.path, 40)}</p>
                </div>
                {ws.active && <Badge variant="success" size="sm">Active</Badge>}
                <button
                  onClick={e => {
                    e.stopPropagation()
                    onDeleteWorkspace(ws.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded text-eternix-400 hover:text-red-400 hover:bg-eternix-800/50 transition-opacity"
                  aria-label="Remove workspace"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
