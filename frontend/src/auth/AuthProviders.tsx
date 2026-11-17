/**
 * Modern authentication controls: Web3 Wallet (SIWE) and WebAuthn Passkeys.
 * Eliminates dead OAuth buttons in favor of non-custodial crypto wallet and biometric auth.
 */
import React, { useState } from 'react'
import {
  browserSupportsWebAuthn,
  startAuthentication,
} from '@simplewebauthn/browser'
import { Fingerprint, Loader2, Wallet } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../context/toast'
import { useAuth } from './AuthProvider'

export const OAUTH_MESSAGE_TYPE = 'dolymarket:oauth'

function friendlyPasskeyError(err: any): string {
  const code = err?.code || err?.name
  if (err?.status === 404 || /unknown passkey/i.test(err?.message || '')) {
    return 'This saved passkey is not linked to an account on this server (old/reset DB). Sign in with Email or Wallet and register a new passkey in Portfolio -> Security.'
  }
  if (code === 'NotAllowedError') {
    return 'Passkey request was cancelled or timed out.'
  }
  if (code === 'InvalidStateError') {
    return 'This passkey is already registered to another account.'
  }
  if (code === 'NotSupportedError') {
    return 'No passkey authenticator is available on this device.'
  }
  return err?.message || 'Passkey sign-in failed'
}

export default function AuthProviders({
  onAuthed,
  compact = false,
}: {
  providers?: any[]
  onAuthed: (user: { id: string; email: string }) => void
  compact?: boolean
}) {
  const { push } = useToast()
  const { loginWithWallet } = useAuth()
  const [busy, setBusy] = useState<string | null>(null)

  async function handleWalletLogin() {
    setBusy('wallet')
    try {
      const ok = await loginWithWallet()
      if (ok) {
        const me = await api.getMe()
        onAuthed({ id: me.id, email: me.email })
      }
    } finally {
      setBusy(null)
    }
  }

  async function signInWithPasskey() {
    setBusy('passkey')
    try {
      if (!browserSupportsWebAuthn()) {
        throw new Error('This browser does not support passkeys.')
      }
      const options = await api.passkeyLoginOptions()
      const assertion = await startAuthentication({
        optionsJSON: options.publicKey,
      })
      const res = await api.passkeyLoginVerify(assertion)
      onAuthed(res.user)
      push('Signed in with your passkey.', 'info')
    } catch (err: any) {
      push(friendlyPasskeyError(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-slate-800" />
        <span className="text-[10px] font-medium uppercase tracking-widest text-slate-500">
          or continue with
        </span>
        <span className="h-px flex-1 bg-slate-800" />
      </div>

      <div className="grid gap-2">
        <button
          type="button"
          disabled={busy !== null}
          onClick={handleWalletLogin}
          className="flex items-center justify-center gap-2.5 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2.5 text-xs font-semibold text-slate-200 transition hover:border-emerald-500/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'wallet' ? (
            <Loader2 className="h-4 w-4 animate-spin text-emerald-400" />
          ) : (
            <Wallet className="h-4 w-4 text-emerald-400" />
          )}
          Sign in with Web3 Wallet (MetaMask / EVM)
        </button>

        <button
          type="button"
          disabled={busy !== null}
          onClick={signInWithPasskey}
          className="flex items-center justify-center gap-2.5 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2.5 text-xs font-semibold text-slate-200 transition hover:border-emerald-500/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'passkey' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Fingerprint className="h-4 w-4 text-cyan-400" />
          )}
          Sign in with Passkey (FaceID / TouchID)
        </button>
      </div>

      <p className="text-center text-[10px] text-slate-500">
        Non-custodial cryptographic authentication. No third-party tracking.
      </p>
    </div>
  )
}
