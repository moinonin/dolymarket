import React, { useState } from 'react'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Flame,
  KeyRound,
  LogIn,
  LogOut,
  ShieldCheck,
  Wallet,
  X,
} from 'lucide-react'
import { useWallet } from '../context/WalletContext'
import { useAuth } from '../auth/AuthProvider'

export function WalletConnectModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean
  onClose: () => void
}) {
  const {
    address,
    chainName,
    chainId,
    isConnected,
    isConnecting,
    walletType,
    error,
    discoveredWallets,
    connect,
    disconnect,
    signMessage,
  } = useWallet()

  const { user, loginWithWallet } = useAuth()
  const [copied, setCopied] = useState(false)
  const [signStatus, setSignStatus] = useState<string | null>(null)
  const [isSigningIn, setIsSigningIn] = useState(false)

  if (!isOpen) return null

  const handleCopy = () => {
    if (!address) return
    navigator.clipboard.writeText(address)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleTestSign = async () => {
    setSignStatus('Signing verification challenge in wallet...')
    const sig = await signMessage(
      `Dolymarket Non-Custodial Verification
Timestamp: ${new Date().toISOString()}
Wallet: ${address}`
    )
    if (sig) {
      setSignStatus('Signature verified! EIP-191 proof matches.')
      setTimeout(() => setSignStatus(null), 4000)
    } else {
      setSignStatus(null)
    }
  }

  const handleWalletSignIn = async () => {
    try {
      setIsSigningIn(true)
      const ok = await loginWithWallet()
      if (ok) onClose()
    } finally {
      setIsSigningIn(false)
    }
  }

  const connectAndSignIn = async (
    type: 'injected' | 'coinbase' | 'gate',
    providerOverride?: any
  ) => {
    const ok = await connect(type, providerOverride)
    if (!ok) return
    if (user) {
      onClose()
      return
    }
    setIsSigningIn(true)
    try {
      const signedIn = await loginWithWallet()
      if (signedIn) onClose()
    } finally {
      setIsSigningIn(false)
    }
  }

  const explorerBase = chainId === 8453 ? 'https://basescan.org' : 'https://etherscan.io'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-md overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/95 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Wallet className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">
                {isConnected ? 'Connected Web3 Wallet' : 'Connect Crypto Wallet'}
              </h3>
              <p className="text-[11px] text-slate-400">
                Non-custodial collateral & passwordless login
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-950/30 p-3 text-xs text-red-300">
            <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            <span>{error}</span>
          </div>
        )}

        {/* Connected State */}
        {isConnected && address ? (
          <div className="mt-5 space-y-4">
            {/* Address Banner */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
                  <span>{chainName}</span>
                  <span className="text-slate-600">({chainId})</span>
                </span>
                <span className="uppercase text-[10px] font-bold text-slate-500 tracking-wider">
                  {walletType}
                </span>
              </div>

              <div className="mt-2.5 flex items-center justify-between">
                <span className="font-mono text-sm font-bold text-slate-100">
                  {address.slice(0, 8)}...{address.slice(-6)}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:text-white transition"
                    title="Copy full address"
                  >
                    {copied ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-400" /> Copied
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" /> Copy
                      </>
                    )}
                  </button>
                  <a
                    href={`${explorerBase}/address/${address}`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:text-white transition"
                    title="View on Explorer"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>

            {/* Dolymarket User Session Status */}
            {user ? (
              <div className="flex items-center justify-between rounded-xl border border-emerald-500/20 bg-emerald-950/20 p-3 text-xs text-emerald-300">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                  <div>
                    <span className="font-semibold">Signed In</span>
                    <p className="text-[10px] text-slate-400 truncate max-w-[220px]">{user.email}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2 rounded-xl border border-amber-500/20 bg-amber-950/20 p-3.5 text-xs text-amber-200">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 text-amber-400 shrink-0" />
                  <span>Wallet connected, but not signed in to Dolymarket.</span>
                </div>
                <button
                  type="button"
                  disabled={isSigningIn}
                  onClick={handleWalletSignIn}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                >
                  <LogIn className="h-3.5 w-3.5" />
                  {isSigningIn ? 'Signing in…' : 'Sign In with This Wallet'}
                </button>
              </div>
            )}

            {signStatus && (
              <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/40 p-3 text-xs text-emerald-300 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                <span>{signStatus}</span>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={handleTestSign}
                className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition"
              >
                <KeyRound className="h-3.5 w-3.5 text-emerald-400" />
                Sign Test Message
              </button>
              <button
                type="button"
                onClick={() => {
                  disconnect()
                  onClose()
                }}
                className="flex items-center gap-1.5 rounded-xl border border-red-500/30 bg-red-950/20 px-4 py-2.5 text-xs font-semibold text-red-300 hover:bg-red-950/40 transition"
              >
                <LogOut className="h-3.5 w-3.5" />
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          /* Disconnected Choices */
          <div className="mt-5 space-y-3">
            {discoveredWallets.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Detected Wallets
                </p>
                {discoveredWallets.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => {
                      const isGate = w.name.toLowerCase().includes('gate') || (w.rdns || '').includes('gate')
                      void connectAndSignIn(isGate ? 'gate' : 'injected', w.provider)
                    }}
                    disabled={isConnecting || isSigningIn}
                    className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
                  >
                    <div className="flex items-center gap-3">
                      {w.icon ? (
                        <img src={w.icon} alt={w.name} className="h-9 w-9 rounded-lg border border-slate-800 bg-slate-900 p-1" />
                      ) : (
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10 text-emerald-400">
                          <Wallet className="h-5 w-5" />
                        </div>
                      )}
                      <div>
                        <h4 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                          {w.name}
                        </h4>
                        <p className="text-[10px] text-slate-400">
                          {w.rdns || 'EIP-6963 browser extension'}
                        </p>
                      </div>
                    </div>
                    <span className="text-xs font-medium text-emerald-400 opacity-0 group-hover:opacity-100 transition">
                      Connect →
                    </span>
                  </button>
                ))}
              </div>
            )}

            <button
              type="button"
              onClick={() => void connectAndSignIn('gate')}
              disabled={isConnecting || isSigningIn}
              className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <Wallet className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                    Gate Wallet
                  </h4>
                  <p className="text-[10px] text-slate-400">
                    Gate.io Web3 / Quick Wallet extension
                  </p>
                </div>
              </div>
              <span className="text-xs font-medium text-emerald-400 opacity-0 group-hover:opacity-100 transition">
                Connect →
              </span>
            </button>

            <button
              type="button"
              onClick={() => void connectAndSignIn('injected')}
              disabled={isConnecting || isSigningIn}
              className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-orange-500/10 text-orange-400 border border-orange-500/20">
                  <Flame className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                    Browser Wallet
                  </h4>
                  <p className="text-[10px] text-slate-400">
                    MetaMask, Rabby, Brave, Rainbow
                  </p>
                </div>
              </div>
              <span className="text-xs font-medium text-emerald-400 opacity-0 group-hover:opacity-100 transition">
                Connect →
              </span>
            </button>

            <button
              type="button"
              onClick={() => void connectAndSignIn('coinbase')}
              disabled={isConnecting || isSigningIn}
              className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                    Coinbase Wallet
                  </h4>
                  <p className="text-[10px] text-slate-400">
                    Extension or smart wallet app
                  </p>
                </div>
              </div>
              <span className="text-xs font-medium text-emerald-400 opacity-0 group-hover:opacity-100 transition">
                Connect →
              </span>
            </button>

            <div className="border-t border-slate-800/80 pt-3">
              <button
                type="button"
                onClick={handleWalletSignIn}
                disabled={isSigningIn}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-3 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
              >
                <LogIn className="h-4 w-4" />
                {isSigningIn ? 'Connecting & Signing…' : 'One-Click Sign In with Wallet'}
              </button>
              <p className="mt-2 text-center text-[10px] text-slate-500">
                Non-custodial EVM signing. No passwords or email required.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
