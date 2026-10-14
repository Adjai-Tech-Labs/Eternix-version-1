import type {
  Conversation,
  ChatMessage,
  Workspace,
  WorkspaceEntry,
  ObjectiveSummary,
  ObjectiveRunResult,
} from '../types'

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

const ACCESS_KEY = 'eternix.access_token'
const REFRESH_KEY = 'eternix.refresh_token'

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(ACCESS_KEY)
  } catch {
    return null
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

export function setTokens(access: string | null, refresh: string | null) {
  try {
    if (access) localStorage.setItem(ACCESS_KEY, access)
    else localStorage.removeItem(ACCESS_KEY)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
    else localStorage.removeItem(REFRESH_KEY)
  } catch {
    // Storage unavailable (private mode); tokens live in memory only.
  }
}

export function clearTokens() {
  setTokens(null, null)
}

let refreshPromise: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!response.ok) return false
    const data = await response.json()
    setTokens(data.access_token, data.refresh_token ?? refresh)
    return true
  } catch {
    return false
  }
}

async function ensureFreshToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

// ---------------------------------------------------------------------------
// Auth-aware fetch
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number
  code: string | null
  detail: unknown

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === 'string'
        ? detail
        : (detail as { message?: string })?.message ?? `HTTP ${status}`
    super(message)
    this.status = status
    this.code = (detail as { code?: string })?.code ?? null
    this.detail = detail
  }
}

async function request<T>(
  url: string,
  options: RequestInit = {},
  { public: isPublic = false, timeout }: { public?: boolean; timeout?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }

  if (!isPublic) {
    const token = getAccessToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  const controller = new AbortController()
  const timeoutId = timeout ? setTimeout(() => controller.abort(), timeout) : null

  try {
    let response = await fetch(`${API_BASE}${url}`, {
      ...options,
      headers,
      signal: controller.signal,
    })

    if (timeoutId) clearTimeout(timeoutId)

    if (response.status === 401 && !isPublic) {
      const refreshed = await ensureFreshToken()
      if (refreshed) {
        const token = getAccessToken()
        if (token) headers['Authorization'] = `Bearer ${token}`
        const controller2 = new AbortController()
        const timeoutId2 = timeout ? setTimeout(() => controller2.abort(), timeout) : null
        response = await fetch(`${API_BASE}${url}`, {
          ...options,
          headers,
          signal: controller2.signal,
        })
        if (timeoutId2) clearTimeout(timeoutId2)
      }
    }

    if (response.status === 401 && !isPublic) {
      window.dispatchEvent(new CustomEvent('eternix:auth:expired'))
      throw new ApiError(401, 'Session expired. Please sign in again.')
    }

    if (!response.ok) {
      const error = await response.json().catch(() => response.statusText)
      throw new ApiError(response.status, error)
    }

    if (response.status === 204) {
      return undefined as T
    }

    return response.json()
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId)
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(408, 'Request timeout')
    }
    throw err
  }
}

const publicRequest = <T>(url: string, options?: RequestInit) =>
  request<T>(url, options, { public: true })

export interface AuthPayload {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  session_id: string
  session_purpose: string
  user: {
    id: string
    username: string | null
    email: string | null
    account_state: string
    payment_eligibility: string
    identities: { provider: string; subject: string; verified: boolean }[]
    required_steps: string[]
  }
}

// ---------------------------------------------------------------------------
// API surface
//
// Only the endpoints the browser shell actually uses are exposed here.
// Raw model, capability and tool inventories stay on the backend: the
// agent selects components on its own and never hands them to the UI.
// ---------------------------------------------------------------------------

export const api = {
  // --- Authentication ---

  authConfig: () =>
    publicRequest<{
      providers: { id: string; name: string; configured: boolean; development_only?: boolean }[]
      google_configured: boolean
      mode: string
      password_policy: {
        min_length: number
        require_digit: boolean
        require_uppercase: boolean
        require_lowercase: boolean
        require_special: boolean
      }
      username_rules: { min_length: number; max_length: number; pattern: string }
      payment: { provider: string; configured: boolean; sandbox: boolean; charges_real_money: boolean }
    }>('/auth/config'),

  registerDev: () =>
    publicRequest<AuthPayload>('/auth/register/dev', { method: 'POST' }),

  checkUsername: (username: string) =>
    publicRequest<{ username: string; available: boolean; error: string | null }>(
      `/auth/username/check?username=${encodeURIComponent(username)}`,
    ),

  completeRegistration: (username: string, password: string, email?: string) =>
    request<AuthPayload>('/auth/register/complete', {
      method: 'POST',
      body: JSON.stringify({ username, password, email }),
    }),

  requestVerification: () =>
    request<{ contact: string; expires_in: number; dev_code: string | null; delivery: string }>(
      '/auth/verify/request',
      { method: 'POST' },
    ),

  confirmVerification: (code: string) =>
    request<AuthPayload>('/auth/verify/confirm', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  paymentStatus: () =>
    publicRequest<{ provider: string; configured: boolean; sandbox: boolean; charges_real_money: boolean }>(
      '/auth/payment/status',
    ),

  paymentSetup: () =>
    request<{ provider: string; setup_id: string; status: string; url: string | null; client_secret: string | null; sandbox: boolean }>(
      '/auth/payment/setup',
      { method: 'POST' },
    ),

  paymentConfirm: (setupId: string) =>
    request<AuthPayload>('/auth/payment/confirm', {
      method: 'POST',
      body: JSON.stringify({ setup_id: setupId }),
    }),

  login: (username: string, password: string) =>
    publicRequest<AuthPayload>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  refresh: (refreshToken?: string) =>
    publicRequest<{ access_token: string; refresh_token: string; session_purpose: string }>(
      '/auth/refresh',
      {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refreshToken ?? getRefreshToken() }),
      },
    ),

  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),

  account: () =>
    request<{
      id: string
      username: string | null
      email: string | null
      account_state: string
      payment_eligibility: string
      identities: { provider: string; subject: string; verified: boolean }[]
      required_steps: string[]
      onboarding_required: boolean
    }>('/auth/account'),

  // --- Conversations ---

  listConversations: () => request<Conversation[]>('/conversations'),

  createConversation: (title: string, objectiveId?: string) =>
    request<{ id: string; title: string; objective_id?: string | null }>(
      '/conversations',
      { method: 'POST', body: JSON.stringify({ title, objective_id: objectiveId }) },
    ),

  getConversation: (conversationId: string) =>
    request<Conversation & { messages: ChatMessage[] }>(`/conversations/${conversationId}`),

  addMessage: (conversationId: string, role: ChatMessage['role'], content: string) =>
    request<{ id: string; conversation_id: string }>(
      `/conversations/${conversationId}/messages`,
      { method: 'POST', body: JSON.stringify({ role, content }) },
    ),

  deleteConversation: (conversationId: string) =>
    request<void>(`/conversations/${conversationId}`, { method: 'DELETE' }),

  renameConversation: (conversationId: string, title: string) =>
    request<{ id: string; title: string }>(`/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),

  // --- Objectives (the agent plans and executes on the backend) ---

  createObjective: (userInput: string) =>
    request<ObjectiveSummary>('/objectives', {
      method: 'POST',
      body: JSON.stringify({ user_input: userInput }),
    }, { timeout: 30000 }),

  getObjective: (objectiveId: string) =>
    request<ObjectiveSummary>(`/objectives/${objectiveId}`),

  runObjective: (objectiveId: string) =>
    request<ObjectiveRunResult>(`/objectives/${objectiveId}/run`, { method: 'POST' }, { timeout: 300000 }),

  stopObjective: (objectiveId: string) =>
    request<{ status: string }>(`/objectives/${objectiveId}/stop`, { method: 'POST' }),

  // --- Workspaces (folders on this machine the agent may use) ---

  registerWorkspace: (path: string, name?: string) =>
    request<Workspace>('/workspace/register', {
      method: 'POST',
      body: JSON.stringify({ path, name }),
    }),

  listWorkspaces: () => request<Workspace[]>('/workspace/list'),

  setActiveWorkspace: (path: string) =>
    request<Workspace>('/workspace/set-active', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  deleteWorkspace: (workspaceId: string) =>
    request<{ status: string }>(`/workspace/${workspaceId}`, { method: 'DELETE' }),

  browseWorkspace: (path?: string) =>
    request<WorkspaceEntry[]>(
      `/workspace/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),

  readWorkspaceFile: (path: string) =>
    request<{ content: string; language: string | null; size: number; path: string }>(
      `/workspace/read?path=${encodeURIComponent(path)}`,
    ),
}
