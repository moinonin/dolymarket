import React, { useCallback, useEffect, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Coins, ExternalLink, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { useToast } from '../context/toast'
import { useWallet } from '../context/WalletContext'
import DexBuilderTransferModal from './DexBuilderTransferModal'

export default function DexBuilderBrokerPanel() {
  const { user } = useAuth()
  const { push } = useToast()
  const { usdcBalance, usdcBalanceLoading, isConnected } = useWallet()
  const [loading, setLoading] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const [transferMode, setTransferMode] = useState<'deposit' | 'withdraw' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [claimable, setClaimable] = useState<{ total_claimable_amount: string; event_count: number } | null>(null)
  const [accountBook, setAccountBook] = useState<any[]>([])
  const [deposits, setDeposits] = useState<any[]>([])
  const [withdrawals, setWithdrawals] = useState<any[]>([])

  const load = useCallback(async () => {
    if (!user?.dexbuilder_wallet) return
    setLoading(true)
    setError(null)
    try {
      const [cl, ab, dep, wdr] = await Promise.all([
        api.getDexBuilderClaimable(),
        api.getDexBuilderAccountBook({ limit: 20 }),
        api.getDexBuilderDeposits(1, 20),
        api.getDexBuilderWithdrawals(1, 20),
      ])
      setClaimable(cl)
      setAccountBook(Array.isArray(ab?.items) ? ab.items : [])
      setDeposits(Array.isArray(dep?.data?.items) ? dep.data.items : [])
      setWithdrawals(Array.isArray(wdr?.data?.items) ? wdr.data.items : [])
    } catch (err: any) {
      setError(err?.message || 'Could not load DexBuilder broker account data')
    } finally {
      setLoading(false)
    }
  }, [user?.dexbuilder_wallet])

  useEffect(() => {
    void load()
  }, [load])

  const handleClaim = async () => {
    setClaiming(true)
    try {
      await api.claimDexBuilderWinnings({})
      push('Claim submitted to DexBuilder', 'info')
      void load()
    } catch (err: any) {
      push(err?.message || 'Claim failed', 'error')
    } finally {
      setClaiming(false)
    }
  }

  if (!user?.dexbuilder_wallet) {
    return (
      <div className="mt-4 flex items-center gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-5 text-xs text-amber-200">
        <ShieldAlert className="h-4 w-4 shrink-0" />
        Connect or bind your DexBuilder wallet to view broker account book, claims, deposits, and withdrawals.
      </div>
    )
  }

  const claimableNum = Number(claimable?.total_claimable_amount ?? 0)

  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex items-center gap-3">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-2.5">
            <Coins className="h-4 w-4 text-emerald-400" />
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">
              DexBuilder Claimable Winnings
            </p>
            <p className="font-mono text-lg font-semibold text-white">
              ${claimable?.total_claimable_amount ?? '0'}
              <span className="ml-2 text-xs font-normal text-slate-400">
                ({claimable?.event_count ?? 0} events)
              </span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isConnected && (
            <span className="rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 font-mono text-xs text-slate-300">
              Wallet USDC: {usdcBalanceLoading ? '…' : usdcBalance !== null ? `$${usdcBalance}` : 'N/A'}
            </span>
          )}
          <button
            onClick={() => setTransferMode('deposit')}
            className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20"
          >
            <ArrowDownToLine className="h-3.5 w-3.5" />
            Deposit USDC
          </button>
          <button
            onClick={() => setTransferMode('withdraw')}
            className="inline-flex items-center gap-1.5 rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20"
          >
            <ArrowUpFromLine className="h-3.5 w-3.5" />
            Withdraw USDC
          </button>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 px-3 py-2 text-xs text-slate-300 transition hover:text-white"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => void handleClaim()}
            disabled={claiming || claimableNum <= 0}
            className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-500 px-4 py-2 text-xs font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {claiming && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Claim all
          </button>
        </div>
      </div>

      {transferMode && (
        <DexBuilderTransferModal
          mode={transferMode}
          onClose={() => setTransferMode(null)}
          onSuccess={() => {
            setTransferMode(null)
            void load()
          }}
        />
      )}

      {error && (
        <div className="rounded-xl border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <HistoryCard title="Account book" empty="No broker ledger entries yet." items={accountBook} />
        <HistoryCard title="Deposits" empty="No on-chain deposits yet." items={deposits} />
        <HistoryCard title="Withdrawals" empty="No on-chain withdrawals yet." items={withdrawals} />
      </div>
    </div>
  )
}

function explorerTxUrl(txHash: string, chainId?: number | null): string {
  switch (chainId) {
    case 1:
      return `https://etherscan.io/tx/${txHash}`
    case 42161:
      return `https://arbiscan.io/tx/${txHash}`
    case 10:
      return `https://optimistic.etherscan.io/tx/${txHash}`
    case 137:
      return `https://polygonscan.com/tx/${txHash}`
    default:
      return `https://basescan.org/tx/${txHash}`
  }
}

function HistoryCard({ title, empty, items }: { title: string; empty: string; items: any[] }) {
  const { chainId } = useWallet()
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-800 py-8 text-center text-xs text-slate-500">
          {empty}
        </div>
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {items.map((item, idx) => {
            const txHash = item.tx_hash || item.txHash || item.hash || null
            const status = String(item.status ?? item.type ?? 'entry')
            const okStatus = /confirm|success|complete|filled/i.test(status)
            return (
              <div key={item.id ?? idx} className="rounded-xl bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                <div className="flex items-center justify-between font-mono">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      okStatus
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : 'bg-slate-800 text-slate-300'
                    }`}
                  >
                    {status}
                  </span>
                  <span className="text-emerald-400">{item.amount ?? item.change ?? '—'}</span>
                </div>
                {(txHash || item.nonce != null) && (
                  <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-slate-500">
                    <span>{item.nonce != null ? `nonce #${item.nonce}` : 'on-chain'}</span>
                    {txHash && (
                      <a
                        href={explorerTxUrl(txHash, item.chain_id ?? chainId)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-blue-300 hover:text-blue-200"
                      >
                        {String(txHash).slice(0, 8)}…{String(txHash).slice(-4)}
                        <ExternalLink className="h-2.5 w-2.5" />
                      </a>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
