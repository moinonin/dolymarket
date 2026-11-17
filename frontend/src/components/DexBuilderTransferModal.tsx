import React, { useEffect, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Loader2, RefreshCw, Wallet, X } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../context/toast'
import { useWallet } from '../context/WalletContext'
import Dialog from './Dialog'

export default function DexBuilderTransferModal({
  mode,
  onClose,
  onSuccess,
}: {
  mode: 'deposit' | 'withdraw'
  onClose: () => void
  onSuccess: () => void
}) {
  const { push } = useToast()
  const {
    address,
    chainId,
    chainName,
    isConnected,
    usdcBalance,
    usdcBalanceLoading,
    refreshUsdcBalance,
    connect,
    signMessage,
    signTypedData,
    sendTransaction,
  } = useWallet()

  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [stepLabel, setStepLabel] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const amt = parseFloat(amount)
  const valid = !Number.isNaN(amt) && amt > 0
  const onChainNum = usdcBalance !== null ? parseFloat(usdcBalance) : null
  const exceedsWallet = mode === 'deposit' && valid && onChainNum !== null && amt > onChainNum

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleSubmit() {
    if (!valid || !isConnected || !address) return
    setBusy(true)
    setError(null)
    const amountStr = amt.toFixed(6).replace(/\.?0+$/, '')

    try {
      if (mode === 'deposit') {
        setStepLabel('Fetching deposit sign data…')
        const raw = await api.createDexBuilderDepositSignData({
          amount: amountStr,
          wallet: address,
          chain_id: chainId,
        })
        const payload = raw?.data ?? raw

        if (payload?.to && payload?.data) {
          setStepLabel('Confirm transaction in wallet…')
          const txHash = await sendTransaction({
            to: payload.to,
            data: payload.data,
            value: payload.value,
          })
          if (!txHash) throw new Error('Deposit transaction was cancelled.')
          push(`On-chain deposit submitted (${txHash.slice(0, 10)}…)`, 'info')
        } else if (payload?.domain && payload?.types && payload?.message) {
          setStepLabel('Sign EIP-712 deposit authorization…')
          const sig = await signTypedData(payload)
          if (!sig) throw new Error('Deposit signature was cancelled.')
          push('Deposit authorization signed.', 'info')
        } else {
          setStepLabel('Sign deposit message in wallet…')
          const msg = typeof payload?.message === 'string' ? payload.message : JSON.stringify(payload)
          const sig = await signMessage(msg)
          if (!sig) throw new Error('Deposit signature was cancelled.')
          push('Deposit message signed.', 'info')
        }
      } else {
        setStepLabel('Fetching withdraw sign data…')
        const raw = await api.createDexBuilderWithdrawSignData({
          amount: amountStr,
          wallet: address,
          chain_id: chainId,
        })
        const payload = raw?.data ?? raw

        let signature: string | null = null
        if (payload?.domain && payload?.types && payload?.message) {
          setStepLabel('Sign EIP-712 withdrawal in wallet…')
          signature = await signTypedData(payload)
        } else {
          setStepLabel('Sign withdrawal message in wallet…')
          const msg = typeof payload?.message === 'string' ? payload.message : JSON.stringify(payload)
          signature = await signMessage(msg)
        }
        if (!signature) throw new Error('Withdrawal signature was cancelled.')

        setStepLabel('Submitting signed withdrawal…')
        await api.submitDexBuilderWithdraw({
          ...payload,
          signature,
          amount: amountStr,
          wallet: address,
          chain_id: chainId,
        })
        push(`Submitted $${amountStr} USDC withdrawal.`, 'info')
      }

      void refreshUsdcBalance()
      onSuccess()
    } catch (err: any) {
      const msg = err?.message || 'On-chain operation failed'
      setError(msg)
      push(msg, 'error')
    } finally {
      setBusy(false)
      setStepLabel(null)
    }
  }

  return (
    <Dialog onClose={onClose} labelledBy="dex-transfer-title">
      <div className="font-geist-mono">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {mode === 'deposit' ? (
              <ArrowDownToLine className="h-5 w-5 text-emerald-400" />
            ) : (
              <ArrowUpFromLine className="h-5 w-5 text-rose-400" />
            )}
            <h2 id="dex-transfer-title" className="text-base font-semibold text-white">
              {mode === 'deposit' ? 'On-Chain USDC Deposit' : 'On-Chain USDC Withdraw'}
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px]">
          {isConnected && address ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-slate-300">
                <span className="flex items-center gap-1.5">
                  <Wallet className="h-3 w-3 text-emerald-400" />
                  <span>Wallet</span>
                </span>
                <span className="font-mono text-emerald-400">
                  {address.slice(0, 6)}...{address.slice(-4)} ({chainName})
                </span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span>On-Chain USDC</span>
                <button
                  type="button"
                  onClick={() => void refreshUsdcBalance()}
                  className="inline-flex items-center gap-1 font-mono text-slate-200 hover:text-emerald-300"
                >
                  <RefreshCw className={`h-2.5 w-2.5 ${usdcBalanceLoading ? 'animate-spin' : ''}`} />
                  {usdcBalanceLoading ? '…' : usdcBalance !== null ? `$${usdcBalance}` : 'N/A'}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between text-slate-400">
              <span>No wallet connected</span>
              <button
                type="button"
                onClick={() => void connect('injected')}
                className="text-emerald-400 underline hover:text-emerald-300"
              >
                Connect Wallet
              </button>
            </div>
          )}
        </div>

        <label htmlFor="dex-transfer-amount" className="block text-[11px] uppercase tracking-wide text-slate-400">
          Amount (USDC)
        </label>
        <input
          id="dex-transfer-amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="25.00"
          inputMode="decimal"
          autoFocus
          className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 font-mono text-sm text-white outline-none focus:border-emerald-500"
        />

        {exceedsWallet && (
          <p className="mt-2 text-xs text-amber-300">
            ⚠ Exceeds on-chain wallet USDC balance (${usdcBalance}).
          </p>
        )}
        {error && (
          <div className="mt-3 rounded-lg border border-rose-800/60 bg-rose-950/40 p-2.5 text-xs text-rose-200">
            {error}
          </div>
        )}
        {stepLabel && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-300">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {stepLabel}
          </p>
        )}

        <button
          type="button"
          disabled={!valid || !isConnected || exceedsWallet || busy}
          onClick={() => void handleSubmit()}
          className={`mt-5 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-bold text-slate-950 transition disabled:cursor-not-allowed disabled:opacity-40 ${
            mode === 'deposit'
              ? 'bg-emerald-500 hover:bg-emerald-400'
              : 'bg-rose-500 hover:bg-rose-400'
          }`}
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {busy
            ? 'Signing…'
            : mode === 'deposit'
              ? 'Sign & Deposit USDC'
              : 'Sign & Withdraw USDC'}
        </button>
      </div>
    </Dialog>
  )
}
