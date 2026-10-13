export interface Conversation {
  id: string
  title: string
  objective_id: string | null
  created_at: string
  updated_at: string
  message_count: number
}

export interface ChatMessage {
  id: string
  conversation_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
}

export interface Workspace {
  id: string
  name: string
  path: string
  active: boolean
  created_at: string
}

export interface WorkspaceEntry {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number | null
  modified: string | null
  language: string | null
}

export interface ObjectiveSummary {
  id: string
  user_input: string
  status: string
}

export interface ObjectiveRunResult {
  status: string
  final_response?: string
  details?: {
    total?: number
    completed?: number
    failed?: number
  }
}
