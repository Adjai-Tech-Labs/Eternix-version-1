import { useEffect, useState } from 'react'
import { cn } from '@/utils/helpers'
import { api } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { ScrollArea } from '@/components/ui/ScrollArea'
import {
  TerminalSquare,
  ShieldCheck,
  KeyRound,
  Mail,
  CreditCard,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Eye,
  EyeOff,
  RefreshCw,
  ArrowRight,
} from 'lucide-react'
import { useAuth, nextOnboardingStep } from '@/contexts/AuthContext'

export function AuthScreen() {
  const { status, account, error } = useAuth()

  useEffect(() => {
    document.documentElement.classList.add('dark')
  }, [])

  if (status === 'loading') {
    return <LoadingScreen />
  }

  if (status === 'unauthenticated') {
    return <SignInScreen />
  }

  // Onboarding: the backend mandates the full registration
  // state machine before any protected resource is accessible.
  const step = account ? nextOnboardingStep(account.accountState) : null
  return (
    <ScrollArea className="min-h-screen w-full">
      <div className="min-h-screen bg-eternix-950 flex flex-col items-center justify-center p-6">
        <BrandHeader />
        <Card variant="elevated" className="w-full max-w-md p-6">
          <StepIndicator step={step} />
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {step === 'credentials' && <CredentialsStep />}
          {step === 'verification' && <VerificationStep />}
          {step === 'payment' && <PaymentStep />}
          {step === null && <CompletionNotice />}
        </Card>
        <p className="mt-6 text-xs text-eternix-500">
          Account security is enforced by the backend. No protected resource is
          accessible before registration completes.
        </p>
      </div>
    </ScrollArea>
  )
}

function LoadingScreen() {
  return (
    <ScrollArea className="min-h-screen w-full">
      <div className="min-h-screen bg-eternix-950 flex flex-col items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-eternix-500" />
        <p className="mt-4 text-sm text-eternix-400">Restoring session...</p>
      </div>
    </ScrollArea>
  )
}

function BrandHeader() {
  return (
    <div className="mb-8 flex flex-col items-center text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-eternix-500 to-eternix-700">
        <TerminalSquare className="h-8 w-8 text-white" />
      </div>
      <h1 className="mt-4 text-2xl font-bold text-eternix-100">ETERNIX</h1>
      <p className="mt-1 text-sm text-eternix-400">Autonomous Agent Platform</p>
    </div>
  )
}

function StepIndicator({ step }: { step: string | null }) {
  const steps = [
    { id: 'credentials', label: 'Account', icon: KeyRound },
    { id: 'verification', label: 'Verify', icon: Mail },
    { id: 'payment', label: 'Payment', icon: CreditCard },
  ]
  const currentIndex = step ? steps.findIndex(s => s.id === step) : steps.length
  return (
    <div className="mb-6 flex items-center justify-between">
      {steps.map((s, index) => {
        const Icon = s.icon
        const done = index < currentIndex
        const current = index === currentIndex
        return (
          <div key={s.id} className="flex items-center">
            <div className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-full border',
                  done && 'border-eternix-500 bg-eternix-500/20 text-eternix-400',
                  current && 'border-eternix-500 bg-eternix-600 text-white',
                  !done && !current && 'border-eternix-700 text-eternix-600',
                )}
              >
                {done ? <CheckCircle2 className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </div>
              <span className={cn('text-xs', current ? 'text-eternix-200' : 'text-eternix-500')}>
                {s.label}
              </span>
            </div>
            {index < steps.length - 1 && (
              <div className={cn('mx-2 h-px w-10', index < currentIndex ? 'bg-eternix-500' : 'bg-eternix-700')} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function SignInScreen() {
  const { login, registerDev, error, clearError } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [devLoading, setDevLoading] = useState(false)
  const [config, setConfig] = useState<{
    google_configured: boolean
    mode: string
    providers: { id: string; name: string; configured: boolean; development_only?: boolean }[]
  } | null>(null)

  useEffect(() => {
    api.authConfig().then(setConfig).catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    setLoading(true)
    try {
      await login(username, password)
    } finally {
      setLoading(false)
    }
  }

  const handleDevRegister = async () => {
    clearError()
    setDevLoading(true)
    try {
      await registerDev()
    } finally {
      setDevLoading(false)
    }
  }

  const devAvailable = config?.providers.some(p => p.id === 'dev' && p.configured) ?? false

  return (
    <ScrollArea className="min-h-screen w-full">
      <div className="min-h-screen bg-eternix-950 flex flex-col items-center justify-center p-6">
        <BrandHeader />
        <Card variant="elevated" className="w-full max-w-md p-6">
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-eternix-200" htmlFor="signin-username">
                Username
              </label>
              <Input
                id="signin-username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="your-username"
                autoComplete="username"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-eternix-200" htmlFor="signin-password">
                Password
              </label>
              <div className="relative">
                <Input
                  id="signin-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-eternix-500 hover:text-eternix-300"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <Button type="submit" variant="primary" className="w-full" disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Sign In'}
            </Button>
          </form>

          {config?.google_configured && (
            <div className="mt-4">
              <Button
                variant="secondary"
                className="w-full"
                onClick={() => {
                  // Google OIDC is initiated by the backend; the
                  // redirect target is the authorization URL.
                  window.location.href = '/auth/google'
                }}
              >
                Continue with Google
              </Button>
            </div>
          )}

          {devAvailable && (
            <div className="mt-6 border-t border-eternix-800 pt-4">
              <div className="mb-3 flex items-center gap-2 text-xs text-eternix-500">
                <ShieldCheck className="h-3.5 w-3.5" />
                Development mode
              </div>
              <Button
                variant="ghost"
                className="w-full"
                onClick={handleDevRegister}
                disabled={devLoading}
              >
                {devLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Create development identity'}
              </Button>
              <p className="mt-2 text-center text-xs text-eternix-500">
                Creates a local identity that still completes the full
                registration, verification and payment-eligibility flow.
              </p>
            </div>
          )}
        </Card>
        <p className="mt-6 flex items-center gap-1.5 text-xs text-eternix-500">
          <ShieldCheck className="h-3.5 w-3.5" />
          Protected by Argon2id hashing, short-lived JWTs and refresh rotation
        </p>
      </div>
    </ScrollArea>
  )
}

function CredentialsStep() {
  const { completeRegistration, clearError } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [usernameCheck, setUsernameCheck] = useState<{ available: boolean; error: string | null } | null>(null)
  const [checking, setChecking] = useState(false)
  const [policy] = useState({ min_length: 8, require_digit: true, require_uppercase: true, require_lowercase: true })

  const checkUsername = async (value: string) => {
    if (value.length < 3) {
      setUsernameCheck(null)
      return
    }
    setChecking(true)
    try {
      const result = await api.checkUsername(value)
      setUsernameCheck({ available: result.available, error: result.error })
    } catch {
      setUsernameCheck(null)
    } finally {
      setChecking(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    setLoading(true)
    try {
      await completeRegistration(username, password, email || undefined)
    } finally {
      setLoading(false)
    }
  }

  const passwordErrors: string[] = []
  if (password.length > 0 && password.length < policy.min_length) {
    passwordErrors.push(`at least ${policy.min_length} characters`)
  }
  if (policy.require_digit && password.length > 0 && !/\d/.test(password)) {
    passwordErrors.push('a digit')
  }
  if (policy.require_uppercase && password.length > 0 && !/[A-Z]/.test(password)) {
    passwordErrors.push('an uppercase letter')
  }
  if (policy.require_lowercase && password.length > 0 && !/[a-z]/.test(password)) {
    passwordErrors.push('a lowercase letter')
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-eternix-400">
        Choose a username and password. A verification code will be sent to your
        email address.
      </p>
      <div className="space-y-2">
        <label className="text-sm font-medium text-eternix-200" htmlFor="reg-username">
          Username
        </label>
        <div className="relative">
          <Input
            id="reg-username"
            value={username}
            onChange={e => {
              setUsername(e.target.value)
              setUsernameCheck(null)
              checkUsername(e.target.value)
            }}
            placeholder="e.g. agent-operator"
            autoComplete="username"
            required
          />
          {checking && <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-eternix-500" />}
          {!checking && usernameCheck && (
            <span className={cn('absolute right-3 top-1/2 -translate-y-1/2', usernameCheck.available ? 'text-emerald-400' : 'text-red-400')}>
              <CheckCircle2 className="h-4 w-4" />
            </span>
          )}
        </div>
        {usernameCheck && !usernameCheck.available && (
          <p className="text-xs text-red-400">{usernameCheck.error}</p>
        )}
      </div>
      <div className="space-y-2">
        <label className="text-sm font-medium text-eternix-200" htmlFor="reg-email">
          Email address
        </label>
        <Input
          id="reg-email"
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          required
        />
      </div>
      <div className="space-y-2">
        <label className="text-sm font-medium text-eternix-200" htmlFor="reg-password">
          Password
        </label>
        <div className="relative">
          <Input
            id="reg-password"
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            required
          />
          <button
            type="button"
            onClick={() => setShowPassword(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-eternix-500 hover:text-eternix-300"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {password.length > 0 && (
          <div className="space-y-1">
            {passwordErrors.length === 0 ? (
              <p className="flex items-center gap-1 text-xs text-emerald-400">
                <CheckCircle2 className="h-3 w-3" /> Password meets policy
              </p>
            ) : (
              <p className="text-xs text-eternix-400">
                Password must contain {passwordErrors.join(', ')}
              </p>
            )}
          </div>
        )}
      </div>
      <Button type="submit" variant="primary" className="w-full" disabled={loading || !usernameCheck?.available}>
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Create account <ArrowRight className="ml-1 h-4 w-4" /></>}
      </Button>
    </form>
  )
}

function VerificationStep() {
  const { requestVerification, confirmVerification, clearError } = useAuth()
  const [code, setCode] = useState('')
  const [contact, setContact] = useState<string | null>(null)
  const [devCode, setDevCode] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [requesting, setRequesting] = useState(false)
  const [requested, setRequested] = useState(false)

  const handleRequest = async () => {
    clearError()
    setRequesting(true)
    try {
      const result = await requestVerification()
      setContact(result.contact)
      setDevCode(result.devCode)
      setRequested(true)
    } finally {
      setRequesting(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    setLoading(true)
    try {
      await confirmVerification(code)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-eternix-400">
        A one-time verification code was sent to your contact method. Enter it
        below to prove control of the address.
      </p>

      {!requested ? (
        <Button variant="primary" className="w-full" onClick={handleRequest} disabled={requesting}>
          {requesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Mail className="mr-2 h-4 w-4" /> Send verification code</>}
        </Button>
      ) : (
        <>
          <div className="rounded-lg border border-eternix-700 bg-eternix-900/50 p-3 text-sm">
            <span className="text-eternix-400">Code sent to </span>
            <span className="font-medium text-eternix-200">{contact ?? 'your contact method'}</span>
          </div>

          {devCode && (
            <div className="rounded-lg border border-eternix-600 bg-eternix-800/50 p-3">
              <p className="text-xs text-eternix-400">Development mode — code delivered in response:</p>
              <p className="mt-1 font-mono text-2xl font-bold tracking-[0.3em] text-eternix-100">{devCode}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-eternix-200" htmlFor="verify-code">
                Verification code
              </label>
              <Input
                id="verify-code"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                inputMode="numeric"
                className="font-mono text-lg tracking-widest"
                autoComplete="one-time-code"
                required
              />
            </div>
            <Button type="submit" variant="primary" className="w-full" disabled={loading || code.length < 6}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Verify contact'}
            </Button>
            <button
              type="button"
              onClick={handleRequest}
              className="flex w-full items-center justify-center gap-1.5 text-xs text-eternix-400 hover:text-eternix-200"
              disabled={requesting}
            >
              <RefreshCw className={cn('h-3 w-3', requesting && 'animate-spin')} />
              Resend code
            </button>
          </form>
        </>
      )}
    </div>
  )
}

function PaymentStep() {
  const { paymentSetup, confirmPayment, account, clearError } = useAuth()
  const [config, setConfig] = useState<{ provider: string; sandbox: boolean; charges_real_money: boolean } | null>(null)
  const [setupId, setSetupId] = useState<string | null>(null)
  const [phase, setPhase] = useState<'idle' | 'creating' | 'confirming' | 'done'>('idle')

  useEffect(() => {
    api.paymentStatus().then(setConfig).catch(() => {})
  }, [])

  const handleStart = async () => {
    clearError()
    setPhase('creating')
    try {
      const id = await paymentSetup()
      setSetupId(id)
      setPhase('done')
    } catch {
      setPhase('idle')
    }
  }

  const handleConfirm = async () => {
    if (!setupId) return
    clearError()
    setPhase('confirming')
    try {
      await confirmPayment(setupId)
    } catch {
      setPhase('done')
    }
  }

  const sandbox = config?.sandbox ?? true
  const ineligible = account?.accountState === 'payment_ineligible'
  const busy = phase === 'creating' || phase === 'confirming'

  return (
    <div className="space-y-4">
      <p className="text-sm text-eternix-400">
        The final mandatory step: register a payment method to activate the
        account. There is deliberately no free tier.
      </p>

      <div className="flex items-center gap-2 rounded-lg border border-eternix-700 bg-eternix-900/50 p-3">
        <CreditCard className="h-4 w-4 text-eternix-400" />
        <span className="text-sm text-eternix-200">
          Provider: <span className="font-medium">{config?.provider ?? 'loading...'}</span>
        </span>
        {sandbox && <Badge variant="info" size="sm">Sandbox — no real charge</Badge>}
      </div>

      {ineligible && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          The previous payment method could not be confirmed. Try again.
        </div>
      )}

      {setupId ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            Payment method registered (setup {setupId.slice(0, 8)}...)
          </div>
          <Button variant="primary" className="w-full" onClick={handleConfirm} disabled={busy}>
            {phase === 'confirming' ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Confirm & activate account <ArrowRight className="ml-1 h-4 w-4" /></>}
          </Button>
        </div>
      ) : (
        <Button variant="primary" className="w-full" onClick={handleStart} disabled={busy}>
          {phase === 'creating' ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Register payment method <ArrowRight className="ml-1 h-4 w-4" /></>}
        </Button>
      )}
    </div>
  )
}

function CompletionNotice() {
  return (
    <div className="flex flex-col items-center py-4 text-center">
      <CheckCircle2 className="h-10 w-10 text-emerald-400" />
      <p className="mt-3 font-medium text-eternix-100">Registration complete</p>
      <p className="mt-1 text-sm text-eternix-400">Loading your workspace...</p>
    </div>
  )
}
