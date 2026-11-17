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
  hasSessionHint,
  setStoredToken,
  setUnauthorizedHandler,
  type OAuthProviderInfo,
} from '../api/client'
import AuthProviders, { OAUTH_MESSAGE_TYPE } from './AuthProviders'
import { useToast } from '../context/toast'
import { useWallet } from '../context/WalletContext'
import Dialog from '../components/Dialog'
import { Wallet, Fingerprint, ChevronDown, ChevronUp } from 'lucide-react'

interface AuthUser {
  id: string
  email: string
  is_admin: boolean
  dexbuilder_wallet?: string | null
}

interface AuthContextValue {
  user: AuthUser | null
  openAuth: (mode: 'login' | 'register') => void
  logout: () => void
  refreshUser: () => Promise<void>
  loginWithWallet: () => Promise<boolean>
  providers: OAuthProviderInfo[]
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  openAuth: () => {},
  logout: () => {},
  refreshUser: async () => {},
  loginWithWallet: async () => false,
  providers: [],
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authModal, setAuthModal] = useState<{ mode: 'login' | 'register' } | null>(null)
  const [providers, setProviders] = useState<OAuthProviderInfo[]>([])
  const { push } = useToast()
  const wallet = useWallet()

  const applyToken = useCallback(async () => {
    let token = getStoredToken()
    if (!token && hasSessionHint()) {
      const refreshed = await api.refreshSession()
      token = refreshed?.access_token ?? null
    }
    if (!token) {
      setUser(null)
      return
    }
    try {
      const me = await api.getMe()
      setUser({
        id: me.id,
        email: me.email,
        is_admin: Boolean(me.is_admin),
        dexbuilder_wallet: me.dexbuilder_wallet ?? null,
      })
    } catch {
      setUser(null)
    }
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.getMe()
      setUser({
        id: me.id,
        email: me.email,
        is_admin: Boolean(me.is_admin),
        dexbuilder_wallet: me.dexbuilder_wallet ?? null,
      })
    } catch {
      setUser(null)
    }
  }, [])

  // Restore the session from the stored token on first paint.
  useEffect(() => {
    void applyToken()
  }, [applyToken])

  // A 401 from any API call means the token expired or was revoked.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  // Tokens carry a 24h exp.
  useEffect(() => {
    const token = getStoredToken()
    if (!token) return
    try {
      const payload = JSON.parse(atob(token.split('.')[1] ?? ''))
      if (typeof payload.exp === 'number' && payload.exp * 1000 < Date.now()) {
        api.logout()
        setUser(null)
      }
    } catch {
      /* unparseable token */
    }
  }, [])

  // Auto-sync wallet address to user account when both exist
  useEffect(() => {
    if (wallet.address && user) {
      api.setDexBuilderWallet(wallet.address).catch((err) => {
        console.warn('Could not auto-sync dexbuilder wallet:', err)
      })
    }
  }, [wallet.address, user?.id])

  // Non-custodial Sign-In with Ethereum (SIWE)
  const loginWithWallet = useCallback(async (): Promise<boolean> => {
    try {
      let activeAddr = wallet.address || localStorage.getItem('dolymarket_wallet_addr')
      if (!activeAddr) {
        const ok = await wallet.connect('injected')
        if (!ok) return false
        activeAddr = localStorage.getItem('dolymarket_wallet_addr')
      }
      if (!activeAddr) {
        throw new Error('No wallet address detected')
      }

      const storedChain = Number(localStorage.getItem('dolymarket_wallet_chain_id'))
      const activeChainId = (Number.isFinite(storedChain) && storedChain > 0 ? storedChain : wallet.chainId) || 8453
      push('Requesting wallet sign-in challenge…', 'info')
      const challengeRes = await api.getWalletChallenge(activeAddr, activeChainId)

      push('Please sign the challenge in your wallet…', 'info')
      const sig = await wallet.signMessage(challengeRes.challenge)
      if (!sig) {
        throw new Error('Signature was rejected or cancelled')
      }

      push('Verifying signature…', 'info')
      const verifyRes = await api.verifyWalletLogin(activeAddr, sig, challengeRes.nonce)

      setStoredToken(verifyRes.access_token)
      setUser({
        id: verifyRes.user.id,
        email: verifyRes.user.email,
        is_admin: Boolean(verifyRes.user.is_admin),
      })
      push('Signed in with Web3 wallet!', 'info')
      return true
    } catch (err: any) {
      push(err.message || 'Wallet sign-in failed', 'error')
      return false
    }
  }, [wallet, push])

  const userRef = {
    user,
    openAuth: (mode: 'login' | 'register') => setAuthModal({ mode }),
    logout: () => {
      api.logout()
      setUser(null)
    },
    refreshUser,
    loginWithWallet,
    providers,
  }

  return (
    <AuthContext.Provider value={userRef}>
      {children}
      {authModal && (
        <AuthModal
          mode={authModal.mode}
          onClose={() => setAuthModal(null)}
          onAuthed={async (u) => {
            setUser({ id: u.id, email: u.email, is_admin: Boolean(u.is_admin) })
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
  onClose: () => void
  onAuthed: (user: { id: string; email: string; is_admin?: boolean }) => void
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function AuthModal({ mode, onClose, onAuthed }: AuthModalProps) {
  const { loginWithWallet } = useAuth()
  const [walletBusy, setWalletBusy] = useState(false)
  const [showEmailForm, setShowEmailForm] = useState(false)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = EMAIL_RE.test(email) && password.length >= 8

  async function handleWalletClick() {
    setWalletBusy(true)
    setError(null)
    try {
      const ok = await loginWithWallet()
      if (ok) onClose()
    } catch (err: any) {
      setError(err.message || 'Wallet sign-in failed')
    } finally {
      setWalletBusy(false)
    }
  }

  async function submitEmail() {
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
    <Dialog onClose={onClose} labelledBy="auth-modal-title">
      <div>
        <h2 id="auth-modal-title" className="text-lg font-bold text-white">
          {mode === 'register' ? 'Join Dolymarket' : 'Welcome Back'}
        </h2>
        <p className="mt-1 text-xs text-slate-400">
          Connect your Web3 crypto wallet for non-custodial, passwordless trading.
        </p>

        {error && (
          <div className="mt-3 rounded-lg border border-red-800/60 bg-red-950/50 px-3 py-2 text-xs text-red-200">
            {error}
          </div>
        )}

        {/* Primary Web3 Wallet Login CTA */}
        <div className="mt-5 space-y-2.5">
          <button
            type="button"
            disabled={walletBusy}
            onClick={handleWalletClick}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-3 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50 shadow-lg shadow-emerald-500/10"
          >
            <Wallet className="h-4 w-4" />
            {walletBusy ? 'Connecting & Signing…' : 'Sign In with Web3 Wallet'}
          </button>

          <AuthProviders onAuthed={onAuthed} compact />
        </div>

        {/* Email & Password Fallback Toggle */}
        <div className="mt-5 border-t border-slate-800/80 pt-4">
          <button
            type="button"
            onClick={() => setShowEmailForm(!showEmailForm)}
            className="flex w-full items-center justify-between text-[11px] font-medium text-slate-400 hover:text-slate-200 transition"
          >
            <span>Or continue with email / dev account</span>
            {showEmailForm ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>

          {showEmailForm && (
            <div className="mt-3 space-y-3">
              <label className="block">
                <span className="text-[11px] font-medium text-slate-400">Email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@dolymarket.internal"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-emerald-500"
                />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium text-slate-400">
                  Password <span className="text-slate-600">(min 8 chars)</span>
                </span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && valid && submitEmail()}
                  placeholder="••••••••"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-emerald-500"
                />
              </label>

              <button
                disabled={!valid || submitting}
                onClick={submitEmail}
                className="w-full rounded-lg bg-slate-800 py-2 text-xs font-semibold text-slate-200 transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting
                  ? 'Please wait…'
                  : mode === 'register'
                    ? 'Create Email Account'
                    : 'Sign In with Email'}
              </button>
            </div>
          )}
        </div>
      </div>
    </Dialog>
  )
}
