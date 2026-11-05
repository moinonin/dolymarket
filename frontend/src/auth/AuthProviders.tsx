/**
 * Federated sign-in controls: Google, Microsoft, Apple and passkeys.
 *
 * OAuth uses the authorization-code flow. The backend redirects the browser
 * to the provider and, once the provider calls back, hands the frontend a
 * one-time code that is exchanged for a JWT. The flow runs in a popup so the
 * trading terminal is never unloaded; if the popup is blocked the same
 * handshake continues in the current tab.
 */
import React, { useState } from 'react'
import {
  browserSupportsWebAuthn,
  startAuthentication,
} from '@simplewebauthn/browser'
import { Fingerprint, Loader2 } from 'lucide-react'
import { api, type OAuthProviderInfo } from '../api/client'
import { useToast } from '../context/toast'

export const OAUTH_MESSAGE_TYPE = 'dolymarket:oauth'

export function ProviderIcon({ name }: { name: string }) {
  if (name === 'google') {
    return (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path
          fill="#4285F4"
          d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.54 5.54 0 0 1-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"
        />
        <path
          fill="#34A853"
          d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.28v3.09A12 12 0 0 0 12 24z"
        />
        <path
          fill="#FBBC05"
          d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.62H1.28a12 12 0 0 0 0 10.76l3.99-3.09z"
        />
        <path
          fill="#EA4335"
          d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.7 0 3.99 2.47 1.28 6.62l3.99 3.09C6.22 6.86 8.87 4.75 12 4.75z"
        />
      </svg>
    )
  }
  if (name === 'microsoft') {
    return (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path fill="#F25022" d="M2 2h9.5v9.5H2z" />
        <path fill="#7FBA00" d="M12.5 2H22v9.5h-9.5z" />
        <path fill="#00A4EF" d="M2 12.5h9.5V22H2z" />
        <path fill="#FFB900" d="M12.5 12.5H22V22h-9.5z" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <path
        fill="currentColor"
        d="M16.36 12.75c-.03-2.6 2.12-3.85 2.22-3.91-1.21-1.77-3.1-2.01-3.77-2.04-1.6-.16-3.13.94-3.94.94-.82 0-2.06-.92-3.4-.9-1.75.03-3.36 1.02-4.26 2.58-1.81 3.14-.46 7.79 1.3 10.34.86 1.25 1.88 2.65 3.23 2.6 1.3-.05 1.79-.84 3.36-.84 1.56 0 2.01.84 3.38.81 1.4-.02 2.28-1.27 3.13-2.53.99-1.45 1.4-2.85 1.42-2.92-.03-.01-2.72-1.05-2.75-4.13zM14.2 5.1c.71-.87 1.19-2.07 1.06-3.27-1.02.04-2.26.68-3 1.55-.66.76-1.24 1.99-1.08 3.16 1.14.09 2.3-.58 3.02-1.44z"
      />
    </svg>
  )
}

function friendlyPasskeyError(err: any): string {
  const code = err?.code || err?.name
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
  providers,
  onAuthed,
  compact = false,
}: {
  providers: OAuthProviderInfo[]
  onAuthed: (user: { id: string; email: string }) => void
  compact?: boolean
}) {
  const { push } = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  async function startOAuth(provider: OAuthProviderInfo) {
    setBusy(provider.name)
    try {
      const start = await api.oauthStart(provider.name, true)
      if (!start.configured) {
        push(
          `${provider.label} sign-in is not configured on this deployment.`,
          'error'
        )
        return
      }
      const popup = window.open(
        start.auth_url,
        'dolymarket-oauth',
        'popup,width=520,height=720'
      )
      if (!popup) {
        push('Popup blocked — continuing sign-in in this tab.', 'info')
        window.location.href = start.auth_url
      }
    } catch (err: any) {
      push(err.message || `Could not start ${provider.label} sign-in`, 'error')
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

  const configured = providers.filter((p) => p.configured)

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-slate-800" />
        <span className="text-[10px] font-medium uppercase tracking-widest text-slate-600">
          or continue with
        </span>
        <span className="h-px flex-1 bg-slate-800" />
      </div>

      <div className="grid gap-2">
        {providers.map((provider) => {
          const disabled = !provider.configured || busy !== null
          return (
            <button
              key={provider.name}
              type="button"
              disabled={disabled}
              onClick={() => startOAuth(provider)}
              className={`flex items-center justify-center gap-2.5 rounded-lg border px-3 py-2.5 text-xs font-semibold transition ${
                provider.configured
                  ? 'border-slate-700 bg-slate-950/60 text-slate-200 hover:border-cyan-500/40 hover:text-white'
                  : 'cursor-not-allowed border-slate-800 bg-slate-950/30 text-slate-600'
              }`}
            >
              {busy === provider.name ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ProviderIcon name={provider.name} />
              )}
              {provider.configured
                ? `Continue with ${provider.label}`
                : `${provider.label} (not configured)`}
            </button>
          )
        })}

        <button
          type="button"
          disabled={busy !== null}
          onClick={signInWithPasskey}
          className="flex items-center justify-center gap-2.5 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2.5 text-xs font-semibold text-slate-200 transition hover:border-cyan-500/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'passkey' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Fingerprint className="h-4 w-4 text-cyan-400" />
          )}
          Sign in with a passkey
        </button>
      </div>

      {configured.length === 0 && (
        <p className="text-center text-[10px] text-slate-600">
          Federated providers need server credentials. Email sign-in always works.
        </p>
      )}
    </div>
  )
}
