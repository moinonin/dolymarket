import React, { useEffect, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Wallet } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../context/toast'
import { useWallet } from '../context/WalletContext'

export default function CashLedgerModal({
  mode,
  available,
  onClose,
  onChanged,
}: {
  mode: 'deposit' | 'withdraw'
  available: number
  onClose: () => void
  onChanged: () => void
}) {
  const { push } = useToast()
  const { address, chainName, isConnected, usdcBalance, usdcBalanceLoading, connect } = useWallet()
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const amt = parseFloat(amount)
  const valid = !Number.isNaN(amt) && amt > 0
  const overdraw = mode === 'withdraw' && valid && amt > available

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function submit() {
    setBusy(true)
    try {
      if (mode === 'deposit') await api.deposit(amt)
      else await api.withdraw(amt)
      push(mode === 'deposit' ? `Deposited $${amt.toFixed(2)} USDC.` : `Withdrew $${amt.toFixed(2)} USDC.`, 'info')
      onChanged()
    } catch (err: any) {
      push(err.message || 'Transaction failed', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cash-ledger-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl font-geist-mono"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center gap-2">
          {mode === 'deposit' ? (
            <ArrowDownToLine className="h-5 w-5 text-emerald-400" />
          ) : (
            <ArrowUpFromLine className="h-5 w-5 text-rose-400" />
          )}
          <h2 id="cash-ledger-title" className="text-lg font-semibold text-white">
            {mode === 'deposit' ? 'Deposit USDC' : 'Withdraw USDC'}
          </h2>
        </div>

        {/* Connected Wallet Bar */}
        <div className="mb-3 rounded-lg border border-slate-800 bg-slate-950/60 p-2 text-[11px]">
          {isConnected && address ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-slate-300">
                <span className="flex items-center gap-1.5">
                  <Wallet className="h-3 w-3 text-emerald-400" />
                  <span>Web3 Source:</span>
                </span>
                <span className="font-mono text-emerald-400">
                  {address.slice(0, 6)}...{address.slice(-4)} ({chainName})
                </span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span>On-Chain USDC:</span>
                <span className="font-mono text-slate-200">
                  {usdcBalanceLoading ? '…' : usdcBalance !== null ? `$${usdcBalance}` : 'N/A'}
                </span>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between text-slate-400">
              <span>No crypto wallet linked</span>
              <button
                type="button"
                onClick={() => connect('injected')}
                className="text-emerald-400 hover:text-emerald-300 underline"
              >
                Connect Wallet
              </button>
            </div>
          )}
        </div>

        <p className="text-xs text-slate-400">
          {mode === 'withdraw'
            ? `Available to withdraw: $${available.toFixed(2)} (unlocked only)`
            : 'Add demo funds in USDC — this is a simulation, no real money moves.'}
        </p>
        <label htmlFor="cash-ledger-amount" className="mt-4 block text-[11px] uppercase tracking-wide text-slate-400">
          Amount (USDC)
        </label>
        <input
          id="cash-ledger-amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="100.00"
          inputMode="decimal"
          autoFocus
          className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 font-mono text-sm outline-none focus:border-emerald-500"
        />
        {overdraw && (
          <p className="mt-2 text-xs text-amber-300">⚠ Exceeds available unlocked balance.</p>
        )}
        <button
          disabled={!valid || overdraw || busy}
          onClick={submit}
          className={`mt-5 w-full rounded-lg py-2.5 text-sm font-bold text-slate-950 transition disabled:cursor-not-allowed disabled:opacity-40 ${
            mode === 'deposit' ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-rose-500 hover:bg-rose-400'
          }`}
        >
          {busy ? 'Processing…' : mode === 'deposit' ? 'Deposit' : 'Withdraw'}
        </button>
      </div>
    </div>
  )
}
