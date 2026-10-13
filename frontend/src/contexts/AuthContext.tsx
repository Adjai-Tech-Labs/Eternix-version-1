import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api, setTokens, clearTokens, getRefreshToken, type AuthPayload } from '../api/client'
export type AuthStatus = 'loading' | 'unauthenticated' | 'onboarding' | 'active'

export interface AccountInfo {
  id: string
  username: string | null
  email: string | null
  accountState: string
  paymentEligibility: string
  identities: { provider: string; subject: string; verified: boolean }[]
  requiredSteps: string[]
}

interface AuthContextType {
  status: AuthStatus
  account: AccountInfo | null
  error: string | null
  login: (username: string, password: string) => Promise<void>
  registerDev: () => Promise<void>
  completeRegistration: (username: string, password: string, email?: string) => Promise<void>
  requestVerification: () => Promise<{ contact: string; devCode: string | null }>
  confirmVerification: (code: string) => Promise<void>
  paymentSetup: () => Promise<string>
  confirmPayment: (setupId: string) => Promise<void>
  logout: () => Promise<void>
  clearError: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

function accountFromPayload(payload: AuthPayload): AccountInfo {
  return {
    id: payload.user.id,
    username: payload.user.username,
    email: payload.user.email,
    accountState: payload.user.account_state,
    paymentEligibility: payload.user.payment_eligibility,
    identities: payload.user.identities,
    requiredSteps: payload.user.required_steps,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [account, setAccount] = useState<AccountInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const applyPayload = useCallback((payload: AuthPayload) => {
    setTokens(payload.access_token, payload.refresh_token)
    const info = accountFromPayload(payload)
    setAccount(info)
    setStatus(info.accountState === 'active' ? 'active' : 'onboarding')
  }, [])

  const loadAccount = useCallback(async () => {
    try {
      const info = await api.account()
      setAccount({
        id: info.id,
        username: info.username,
        email: info.email,
        accountState: info.account_state,
        paymentEligibility: info.payment_eligibility,
        identities: info.identities,
        requiredSteps: info.required_steps,
      })
      setStatus(info.account_state === 'active' ? 'active' : 'onboarding')
    } catch {
      // No valid session.
      setStatus('unauthenticated')
      setAccount(null)
    }
  }, [])

  // Initial session restore: use stored tokens, attempt refresh when
  // the access token is expired. Without a stored refresh credential
  // there is no session to restore, so no probe is made.
  useEffect(() => {
    const bootstrap = async () => {
      if (!getRefreshToken()) {
        setStatus('unauthenticated')
        return
      }
      try {
        await loadAccount()
      } catch {
        setStatus('unauthenticated')
      }
    }
    bootstrap()
  }, [loadAccount])

  // Surface expired sessions everywhere.
  useEffect(() => {
    const handler = () => {
      clearTokens()
      setAccount(null)
      setStatus('unauthenticated')
    }
    window.addEventListener('eternix:auth:expired', handler)
    return () => window.removeEventListener('eternix:auth:expired', handler)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setError(null)
    try {
      const payload = await api.login(username, password)
      applyPayload(payload)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign-in failed'
      setError(message)
      throw err
    }
  }, [applyPayload])

  const registerDev = useCallback(async () => {
    setError(null)
    try {
      const payload = await api.registerDev()
      applyPayload(payload)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Registration unavailable'
      setError(message)
      throw err
    }
  }, [applyPayload])

  const completeRegistration = useCallback(
    async (username: string, password: string, email?: string) => {
      setError(null)
      try {
        const payload = await api.completeRegistration(username, password, email)
        applyPayload(payload)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Registration failed'
        setError(message)
        throw err
      }
    },
    [applyPayload],
  )

  const requestVerification = useCallback(async () => {
    setError(null)
    try {
      const result = await api.requestVerification()
      return { contact: result.contact, devCode: result.dev_code }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Verification request failed'
      setError(message)
      throw err
    }
  }, [])

  const confirmVerification = useCallback(
    async (code: string) => {
      setError(null)
      try {
        const payload = await api.confirmVerification(code)
        applyPayload(payload)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Verification failed'
        setError(message)
        throw err
      }
    },
    [applyPayload],
  )

  const paymentSetup = useCallback(async () => {
    setError(null)
    try {
      const result = await api.paymentSetup()
      return result.setup_id
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Payment setup unavailable'
      setError(message)
      throw err
    }
  }, [])

  const confirmPayment = useCallback(
    async (setupId: string) => {
      setError(null)
      try {
        const payload = await api.paymentConfirm(setupId)
        applyPayload(payload)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Payment confirmation failed'
        setError(message)
        throw err
      }
    },
    [applyPayload],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // Local cleanup proceeds regardless of the server response.
    }
    clearTokens()
    setAccount(null)
    setStatus('unauthenticated')
  }, [])

  const clearError = useCallback(() => setError(null), [])

  const value = useMemo<AuthContextType>(
    () => ({
      status,
      account,
      error,
      login,
      registerDev,
      completeRegistration,
      requestVerification,
      confirmVerification,
      paymentSetup,
      confirmPayment,
      logout,
      clearError,
    }),
    [
      status,
      account,
      error,
      login,
      registerDev,
      completeRegistration,
      requestVerification,
      confirmVerification,
      paymentSetup,
      confirmPayment,
      logout,
      clearError,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

/** The next mandatory onboarding step for the current account state. */
export function nextOnboardingStep(accountState: string): 'credentials' | 'verification' | 'payment' | null {
  switch (accountState) {
    case 'registration_incomplete':
      return 'credentials'
    case 'awaiting_verification':
      return 'verification'
    case 'awaiting_payment_method':
    case 'payment_ineligible':
      return 'payment'
    default:
      return null
  }
}

export function hasStoredSession(): boolean {
  return Boolean(getRefreshToken())
}
