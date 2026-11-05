import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import {
  api,
  getStoredToken,
  setStoredToken,
  type OAuthProviderInfo,
} from '../api/client'
import AuthProviders, { OAUTH_MESSAGE_TYPE } from './AuthProviders'
import { useToast } from '../context/toast'

interface AuthUser {
  id: string
  email: string
}

interface AuthContextValue {
  user: AuthUser | null
  openAuth: (mode: 'login' | 'register') => void
  logout: () => void
  refreshUser: () => Promise<void>
  providers: OAuthProviderInfo[]
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  openAuth: () => {},
  logout: () => {},
  refreshUser: async () => {},
  providers: [],
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authModal, setAuthModal] = useState<{ mode: 'login' | 'register' } | null>(null)
  const [providers, setProviders] = useState<OAuthProviderInfo[]>([])
  const { push } = useToast()

  const applyToken = useCallback(async () => {
    const token = getStoredToken()
    if (!token) {
      setUser(null)
      return
    }
    try {
      const me = await api.getMe()
      setUser({ id: me.id, email: me.email })
    } catch {
      setUser(null)
    }
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.getMe()
      setUser({ id: me.id, email: me.email })
    } catch {
      setUser(null)
    }
  }, [])

  // Restore the session from the stored token on first paint.
  useEffect(() => {
    void applyToken()
  }, [applyToken])

  // Which federated providers this deployment supports.
  useEffect(() => {
    let cancelled = false
    api
      .listAuthProviders()
      .then((res) => {
        if (!cancelled) setProviders(res.providers)
      })
      .catch(() => {
        if (!cancelled) setProviders([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Federated sign-in hand-off: the popup (or this tab) receives a one-time
  // code, redeems it for a JWT and notifies the opener window.
  useEffect(() => {
    async function complete(code: string) {
      try {
        const res = await api.oauthExchange(code)
        setUser({ id: res.user.id, email: res.user.email })
        if (window.opener) {
          window.opener.postMessage(
            { type: OAUTH_MESSAGE_TYPE, token: res.access_token, user: res.user },
            window.location.origin
          )
          window.close()
        }
      } catch (err: any) {
        push(err.message || 'Federated sign-in failed', 'error')
      }
    }

    const params = new URLSearchParams(window.location.search)
    const code = params.get('oauth_code')
    if (code) {
      window.history.replaceState(
        {},
        document.title,
        window.location.pathname + window.location.hash
      )
      void complete(code)
    }

    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return
      const data = event.data
      if (data?.type !== OAUTH_MESSAGE_TYPE || !data?.token) return
      setStoredToken(data.token)
      setUser({ id: data.user.id, email: data.user.email })
    }

    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [push])

  const userRef = {
    user,
    openAuth: (mode: 'login' | 'register') => setAuthModal({ mode }),
    logout: () => {
      api.logout()
      setUser(null)
    },
    refreshUser,
    providers,
  }

  return (
    <AuthContext.Provider value={userRef}>
      {children}
      {authModal && (
        <AuthModal
          mode={authModal.mode}
          providers={providers}
          onClose={() => setAuthModal(null)}
          onAuthed={async (u) => {
            setUser({ id: u.id, email: u.email })
            setAuthModal(null)
          }}
        />
      )}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

interface AuthModalProps {
  mode: 'login' | 'register'
  providers: OAuthProviderInfo[]
  onClose: () => void
  onAuthed: (user: { id: string; email: string }) => void
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function AuthModal({ mode, providers, onClose, onAuthed }: AuthModalProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = EMAIL_RE.test(email) && password.length >= 8

  async function submit() {
    if (!valid) return
    setSubmitting(true)
    setError(null)
    try {
      const res =
        mode === 'register'
          ? await api.register(email, password)
          : await api.login(email, password)
      onAuthed(res.user)
    } catch (err: any) {
      setError(err.message || 'Authentication failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-white">
          {mode === 'register' ? 'Create trader account' : 'Sign in'}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          {mode === 'register'
            ? 'Register to trade, deposit collateral and receive fill notifications.'
            : 'Welcome back. Enter your credentials to access your portfolio.'}
        </p>
        <div className="mt-5 space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-slate-400">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-400">
              Password <span className="text-slate-600">(min 8 chars)</span>
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && valid && submit()}
              placeholder="••••••••"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500"
            />
          </label>
        </div>
        {error && (
          <div className="mt-3 rounded-lg border border-red-800/60 bg-red-950/50 px-3 py-2 text-xs text-red-200">
            {error}
          </div>
        )}
        <button
          disabled={!valid || submitting}
          onClick={submit}
          className="mt-5 w-full rounded-lg bg-emerald-500 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting
            ? 'Please wait…'
            : mode === 'register'
              ? 'Create Account'
              : 'Sign In'}
        </button>
        {mode === 'register' && (
          <p className="mt-3 text-center text-xs text-slate-500">
            Demo trader preset: <span className="text-slate-300">trader@demo.io</span> /{' '}
            <span className="text-slate-300">trader-demo-1234</span>
          </p>
        )}

        <div className="mt-5">
          <AuthProviders providers={providers} onAuthed={onAuthed} />
        </div>
      </div>
    </div>
  )
}
