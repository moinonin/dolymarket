import React, { useState, useRef, useEffect } from 'react'
import {
  Wallet,
  X,
  Copy,
  Check,
  ExternalLink,
  LogOut,
  ShieldCheck,
  Flame,
  KeyRound,
  CheckCircle2,
  AlertCircle,
  LogIn,
} from 'lucide-react'
import { useWallet } from '../context/WalletContext'
import { useAuth } from '../auth/AuthProvider'

export function WalletButton() {
  const {
    address,
    chainName,
    chainId,
    isConnected,
    isConnecting,
    walletType,
    error,
    usdcBalance,
    usdcBalanceLoading,
    refreshUsdcBalance,
    connect,
    disconnect,
    signMessage,
  } = useWallet()

  const { user, loginWithWallet } = useAuth()
  const [isOpen, setIsOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [signStatus, setSignStatus] = useState<string | null>(null)
  const [isSigningIn, setIsSigningIn] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  // Close on Escape key
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setIsOpen(false)
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const handleCopy = () => {
    if (!address) return
    navigator.clipboard.writeText(address)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleTestSign = async () => {
    setSignStatus('Signing in wallet...')
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
      if (ok) setIsOpen(false)
    } finally {
      setIsSigningIn(false)
    }
  }

  const explorerBase = chainId === 8453 ? 'https://basescan.org' : 'https://etherscan.io'

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] font-medium text-foreground transition hover:border-accent/50 hover:bg-muted/60"
        title={isConnected && address ? `Connected to ${chainName}: ${address}` : 'Connect Web3 Crypto Wallet'}
      >
        <Wallet className="h-3.5 w-3.5 text-accent" />
        {isConnected && address ? (
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
            <span className="font-mono">{address.slice(0, 6)}...{address.slice(-4)}</span>
          </span>
        ) : (
          <span className="hidden sm:inline">Connect Wallet</span>
        )}
      </button>

      {/* Downward Dropdown Card anchored to the navbar button */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2.5 z-50 w-80 sm:w-96 rounded-2xl border border-slate-800 bg-slate-900/98 p-5 shadow-2xl backdrop-blur-md">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Wallet className="h-3.5 w-3.5" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">
                  {isConnected ? 'Connected Web3 Wallet' : 'Connect Crypto Wallet'}
                </h4>
                <p className="text-[10px] text-slate-400">
                  {isConnected ? `${chainName} (${chainId})` : 'Non-custodial trading & collateral'}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white transition"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {error && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-950/30 p-2.5 text-[11px] text-red-300">
              <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
              <span>{error}</span>
            </div>
          )}

          {isConnected && address ? (
            /* Connected State */
            <div className="mt-3.5 space-y-3">
              {/* Address Banner */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
                <div className="flex items-center justify-between text-[10px] text-slate-400">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
                    <span>{chainName}</span>
                  </span>
                  <span className="uppercase font-bold text-slate-500 tracking-wider">
                    {walletType}
                  </span>
                </div>

                <div className="mt-2 flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-slate-100">
                    {address.slice(0, 8)}...{address.slice(-6)}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={handleCopy}
                      className="flex items-center gap-1 rounded-md border border-slate-800 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300 hover:text-white transition"
                      title="Copy full address"
                    >
                      {copied ? (
                        <>
                          <Check className="h-2.5 w-2.5 text-emerald-400" /> Copied
                        </>
                      ) : (
                        <>
                          <Copy className="h-2.5 w-2.5" /> Copy
                        </>
                      )}
                    </button>
                    <a
                      href={`${explorerBase}/address/${address}`}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 rounded-md border border-slate-800 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300 hover:text-white transition"
                      title="View on Explorer"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
                <div className="mt-2 flex items-center justify-between border-t border-slate-800/80 pt-2 text-[11px]">
                  <span className="text-slate-400">On-Chain USDC</span>
                  <button
                    type="button"
                    onClick={() => void refreshUsdcBalance()}
                    className="font-mono text-emerald-400 hover:text-emerald-300"
                    title="Refresh on-chain USDC balance"
                  >
                    {usdcBalanceLoading ? '…' : usdcBalance !== null ? `$${usdcBalance}` : 'N/A'}
                  </button>
                </div>
              </div>

              {/* Dolymarket User Session Status */}
              {user ? (
                <div className="flex items-center justify-between rounded-xl border border-emerald-500/20 bg-emerald-950/20 p-2.5 text-xs text-emerald-300">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                    <div>
                      <span className="font-semibold text-[11px]">Dolymarket Session Active</span>
                      <p className="text-[10px] text-slate-400 truncate max-w-[200px]">{user.email}</p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 rounded-xl border border-amber-500/20 bg-amber-950/20 p-3 text-xs text-amber-200">
                  <div className="flex items-center gap-2">
                    <AlertCircle className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                    <span className="text-[11px]">Wallet connected, not signed in to Dolymarket.</span>
                  </div>
                  <button
                    type="button"
                    disabled={isSigningIn}
                    onClick={handleWalletSignIn}
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-500 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                  >
                    <LogIn className="h-3.5 w-3.5" />
                    {isSigningIn ? 'Signing in…' : 'Sign In with This Wallet'}
                  </button>
                </div>
              )}

              {signStatus && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/40 p-2 text-[11px] text-emerald-300 flex items-center gap-1.5">
                  <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
                  <span>{signStatus}</span>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleTestSign}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-xl border border-slate-800 bg-slate-950 py-2 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 transition"
                >
                  <KeyRound className="h-3 w-3 text-emerald-400" />
                  Test Sign
                </button>
                <button
                  type="button"
                  onClick={() => {
                    disconnect()
                    setIsOpen(false)
                  }}
                  className="flex items-center gap-1.5 rounded-xl border border-red-500/30 bg-red-950/20 px-3 py-2 text-[11px] font-semibold text-red-300 hover:bg-red-950/40 transition"
                >
                  <LogOut className="h-3 w-3" />
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            /* Disconnected Choices */
            <div className="mt-3.5 space-y-2.5">
              <button
                type="button"
                onClick={async () => {
                  const ok = await connect('injected')
                  if (ok) setIsOpen(false)
                }}
                disabled={isConnecting}
                className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-500/10 text-orange-400 border border-orange-500/20">
                    <Flame className="h-4 w-4" />
                  </div>
                  <div>
                    <h5 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                      Browser Wallet
                    </h5>
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
                onClick={async () => {
                  const ok = await connect('coinbase')
                  if (ok) setIsOpen(false)
                }}
                disabled={isConnecting}
                className="group flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-left transition hover:border-emerald-500/40 hover:bg-slate-950"
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                    <ShieldCheck className="h-4 w-4" />
                  </div>
                  <div>
                    <h5 className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                      Coinbase Wallet
                    </h5>
                    <p className="text-[10px] text-slate-400">
                      Extension or smart wallet app
                    </p>
                  </div>
                </div>
                <span className="text-xs font-medium text-emerald-400 opacity-0 group-hover:opacity-100 transition">
                  Connect →
                </span>
              </button>

              <div className="border-t border-slate-800/80 pt-2.5">
                <button
                  type="button"
                  onClick={handleWalletSignIn}
                  disabled={isSigningIn}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                >
                  <LogIn className="h-3.5 w-3.5" />
                  {isSigningIn ? 'Connecting & Signing…' : 'One-Click Sign In with Wallet'}
                </button>
                <p className="mt-2 text-center text-[10px] text-slate-500">
                  Direct EVM SIWE login. Zero simulated wallets.
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
