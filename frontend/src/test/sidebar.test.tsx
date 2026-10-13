import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from '@/components/Sidebar'
import type { Conversation, Workspace } from '@/types'

const conversations: Conversation[] = [
  {
    id: 'c1',
    title: 'First chat',
    objective_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 3,
  },
  {
    id: 'c2',
    title: 'Second chat',
    objective_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 1,
  },
]

const workspaces: Workspace[] = [
  {
    id: 'w1',
    name: 'Projects',
    path: '/home/user/projects',
    active: true,
    created_at: new Date().toISOString(),
  },
]

const baseProps = {
  conversations,
  activeConversationId: 'c1',
  onSelectConversation: vi.fn(),
  onDeleteConversation: vi.fn(),
  onRenameConversation: vi.fn(),
  onNewChat: vi.fn(),
  workspaces,
  onSelectWorkspace: vi.fn(),
  onDeleteWorkspace: vi.fn(),
  onAddWorkspace: vi.fn(),
}

describe('Sidebar', () => {
  it('shows the Eternix brand and New Chat button', () => {
    render(<Sidebar {...baseProps} />)
    expect(screen.getByText('Eternix')).toBeInTheDocument()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
  })

  it('lists previous chats', () => {
    render(<Sidebar {...baseProps} />)
    expect(screen.getByText('First chat')).toBeInTheDocument()
    expect(screen.getByText('Second chat')).toBeInTheDocument()
  })

  it('lists workspaces with the active one marked', () => {
    render(<Sidebar {...baseProps} />)
    expect(screen.getByText('Projects')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('calls onNewChat when New Chat is clicked', () => {
    render(<Sidebar {...baseProps} />)
    fireEvent.click(screen.getByText('New Chat'))
    expect(baseProps.onNewChat).toHaveBeenCalled()
  })

  it('opens the add-workspace dialog via the folder button', () => {
    render(<Sidebar {...baseProps} />)
    fireEvent.click(screen.getByLabelText('Add workspace folder'))
    expect(baseProps.onAddWorkspace).toHaveBeenCalled()
  })

  it('selects a workspace when clicked', () => {
    render(<Sidebar {...baseProps} />)
    fireEvent.click(screen.getByText('Projects'))
    expect(baseProps.onSelectWorkspace).toHaveBeenCalledWith(workspaces[0])
  })
})
