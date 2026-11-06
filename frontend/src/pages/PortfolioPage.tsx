import React, { useEffect, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  CircleDollarSign,
  Clock,
  Fingerprint,
  KeyRound,
  Loader2,
  Lock,
  ShieldCheck,
  Trash2,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import { startRegistration } from '@simplewebauthn/browser'
import {
  api,
  type Balance,
  type LedgerEntry,
  type Order,
  type PasskeyCredentialInfo,
  type Position,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { Skeleton, StatusPill } from '../components/ui'
import { subscribePendingOrders } from '../api/optimisticOrders'
import { useToast } from '../context/toast'
import CashLedgerModal from '../components/CashLedgerModal'

type Tab = 'positions' | 'settled' | 'orders' | 'trades' | 'ledger' | 'security'

const TABS: { key: Tab; label: string }[] = [
  { key: 'positions', label: 'Active Positions' },
  { key: 'settled', label: 'Settled & Redemption' },
  { key: 'orders', label: 'Open Orders' },
  { key: 'trades', label: 'Execution History' },
  { key: 'ledger', label: 'Cash Ledger' },
  { key: 'security', label: 'Security' },
]

export default function PortfolioPage({ onOpenEvent }: { onOpenEvent: (slug: string) => void }) {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('positions')
  const [balance, setBalance] = useState<Balance | null>(null)
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [orders, setOrders] = useState<Order[] | null>(null)
  const [tradeFills, setTradeFills] = useState<any[] | null>(null)
  const [ledger, setLedger] = useState<LedgerEntry[] | null>(null)
  const [ledgerModal, setLedgerModal] = useState<'deposit' | 'withdraw' | null>(null)
  const [loading, setLoading] = useState(true)
  const [pendingOrders, setPendingOrders] = useState<Order[]>([])

  useEffect(() => subscribePendingOrders(setPendingOrders), [])

  async function refresh() {
    if (!user) return
    setLoading(true)
    try {
      const [bal, pos, ord, led] = await Promise.all([
        api.getBalance(),
        api.listPositions().catch(() => ({ positions: [] })),
        api.listOrders({ limit: 100 }).catch(() => ({ orders: [] })),
        api.getLedger().catch(() => ({ entries: [] })),
      ])
      setBalance(bal)
      setPositions(pos.positions)
      setOrders(ord.orders)
      setLedger(led.entries)
      // Execution history: all orders that have fills.
      const filled = ord.orders.filter((o) => o.filled_amount > 0)
      setTradeFills(filled)
    } catch (err: any) {
      // toast surfaced by client
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (user) refresh()
  }, [user?.id])

  if (!user) {
    return (
      <div className="mx-auto max-w-3xl px-6 pt-32 text-center">
        <Wallet className="mx-auto mb-4 h-10 w-10 text-slate-600" />
        <h2 className="text-lg font-semibold text-white">Your portfolio lives here</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
          Sign in to track positions, open orders, execution history, and to claim winning
          payouts once markets resolve.
        </p>
      </div>
    )
  }

  const openPositions = (positions || []).filter(
    (p) => !p.is_settled && !p.claimed && p.shares > 0
  )
  const settledPositions = (positions || []).filter(
    (p) => p.market_status === 'RESOLVED'
  )
  const activeOrders = [
    ...pendingOrders,
    ...(orders || []).filter(
      (o) =>
        (o.status === 'OPEN' || o.status === 'PARTIALLY_FILLED') &&
        !pendingOrders.some((pending) => pending.id === o.id)
    ),
  ]
  const totalUnrealized = (openPositions || []).reduce(
    (acc, p) => acc + (p.unrealized_pnl || 0),
    0
  )
  const portfolioValue =
    (openPositions || []).reduce(
      (acc, p) => acc + p.shares * (p.current_price ?? p.avg_entry_price),
      0
    ) + (balance?.balance ?? 0)

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      {/* Summary cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryCard
          icon={<TrendingUp className="h-4 w-4 text-blue-400" />}
          label="Portfolio Value"
          value={loading ? null : `$${portfolioValue.toFixed(2)}`}
        />
        <SummaryCard
          icon={<CircleDollarSign className="h-4 w-4 text-emerald-400" />}
          label="Available USDC"
          value={loading ? null : `$${(balance?.balance ?? 0).toFixed(2)}`}
          action={() => setLedgerModal('deposit')}
          actionLabel="Deposit"
        />
        <SummaryCard
          icon={<Lock className="h-4 w-4 text-amber-400" />}
          label="Locked in Orders"
          value={loading ? null : `$${(balance?.locked_balance ?? 0).toFixed(2)}`}
        />
        <SummaryCard
          icon={<ArrowUpRight className="h-4 w-4 text-emerald-400" />}
          label="Unrealized PnL"
          value={
            loading
              ? null
              : `${totalUnrealized >= 0 ? '+' : ''}$${totalUnrealized.toFixed(2)}`
          }
          tone={totalUnrealized >= 0 ? 'up' : 'down'}
        />
        <SummaryCard
          icon={<Clock className="h-4 w-4 text-slate-300" />}
          label="Open Orders"
          value={loading ? null : `${activeOrders.length}`}
        />
      </div>

      {/* Tabs */}
      <div className="mt-8 flex flex-wrap gap-1.5 border-b border-slate-800 pb-0 sm:flex-nowrap sm:overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`whitespace-nowrap rounded-t-lg px-4 py-2.5 text-xs font-medium transition ${
              tab === t.key
                ? 'border-b-2 border-emerald-400 text-white'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="pt-6">
        {tab === 'positions' && (
          <PositionsTable
            positions={openPositions}
            loading={loading}
            onOpenEvent={onOpenEvent}
            onChanged={refresh}
          />
        )}
        {tab === 'settled' && (
          <SettledTable positions={settledPositions} loading={loading} onChanged={refresh} />
        )}
        {tab === 'orders' && (
          <OrdersTable orders={activeOrders} loading={loading} onChanged={refresh} />
        )}
        {tab === 'trades' && <TradesTable fills={tradeFills} loading={loading} />}
        {tab === 'ledger' && <LedgerTable entries={ledger} loading={loading} />}
        {tab === 'security' && <SecurityPanel />}
      </div>

      {ledgerModal && balance && (
        <CashLedgerModal
          mode={ledgerModal}
          available={balance.balance - balance.locked_balance}
          onClose={() => setLedgerModal(null)}
          onChanged={() => {
            setLedgerModal(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function SummaryCard({
  icon,
  label,
  value,
  tone,
  action,
  actionLabel,
}: {
  icon: React.ReactNode
  label: string
  value: string | null
  tone?: 'up' | 'down'
  action?: () => void
  actionLabel?: string
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
          {icon}
          {label}
        </div>
        {action && (
          <button
            onClick={action}
            className="rounded-md border border-slate-700 px-2 py-0.5 text-[10px] font-medium text-slate-300 transition hover:border-emerald-500/50 hover:text-emerald-300"
          >
            {actionLabel}
          </button>
        )}
      </div>
      <div
        className={`mt-2 font-mono text-xl font-semibold ${
          tone === 'up' ? 'text-emerald-400' : tone === 'down' ? 'text-rose-400' : 'text-white'
        }`}
      >
        {value == null ? <Skeleton className="h-6 w-24" /> : value}
      </div>
    </div>
  )
}

function PositionsTable({
  positions,
  loading,
  onOpenEvent,
  onChanged,
}: {
  positions: Position[]
  loading: boolean
  onOpenEvent: (slug: string) => void
  onChanged: () => void
}) {
  const { push } = useToast()
  const [closing, setClosing] = useState<string | null>(null)

  async function closePosition(p: Position) {
    setClosing(p.position_id)
    try {
      await api.mergePositions(p.market_id, p.shares)
      push('Position closed: full outcome set merged back into USDC.', 'info')
      onChanged()
    } catch {
      try {
        const orders = await api.listOrders({ market_id: p.market_id, limit: 100 })
        // Fall back: place a SELL order at current bid
        await api.submitOrder({
          market_id: p.market_id,
          token_id: p.token_id,
          side: 'SELL',
          type: 'MARKET',
          price: p.current_price,
          amount: p.shares,
          time_in_force: 'IOC',
          post_only: false,
        })
        push('Sell order routed to the book.', 'info')
        onChanged()
      } catch (err: any) {
        push(err.message || 'Failed to close position', 'error')
      }
    } finally {
      setClosing(null)
    }
  }

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )
  }
  if (positions.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
        <p className="text-sm font-medium text-slate-300">No active positions</p>
        <p className="mt-1 text-xs text-slate-500">
          Buy outcome tokens from any market page and they appear here.
        </p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <Th>Market</Th>
            <Th>Token</Th>
            <Th right>Shares</Th>
            <Th right>Entry</Th>
            <Th right>Current</Th>
            <Th right>Value</Th>
            <Th right>Unrealized PnL</Th>
            <Th right>Action</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70">
          {positions.map((p) => {
            const cur = p.current_price ?? p.avg_entry_price
            const value = p.shares * cur
            const pnl = p.unrealized_pnl ?? (cur - p.avg_entry_price) * p.shares
            const pnlPct = p.avg_entry_price > 0 ? (pnl / (p.avg_entry_price * p.shares)) * 100 : 0
            return (
              <tr key={p.position_id} className="transition hover:bg-slate-900/50">
                <Td>
                  <button
                    onClick={() => p.event_slug && onOpenEvent(p.event_slug)}
                    className="text-left font-medium text-slate-200 hover:text-emerald-300"
                  >
                    {p.event_title || p.market_question || '—'}
                  </button>
                  <div className="text-[10px] text-slate-500">{p.market_question}</div>
                </Td>
                <Td><TokenChip symbol={p.outcome_symbol || '—'} /></Td>
                <Td right mono>{p.shares.toFixed(1)}</Td>
                <Td right mono>¢{(p.avg_entry_price * 100).toFixed(1)}</Td>
                <Td right mono>{cur != null ? `¢${(cur * 100).toFixed(1)}` : '—'}</Td>
                <Td right mono>${value.toFixed(2)}</Td>
                <Td right>
                  <span className={`font-mono ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} ({pnl >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)
                  </span>
                </Td>
                <Td right>
                  <button
                    disabled={closing === p.position_id}
                    onClick={() => closePosition(p)}
                    className="rounded-md border border-rose-500/40 px-2.5 py-1 text-[10px] font-medium text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-40"
                  >
                    {closing === p.position_id ? 'Closing…' : 'Sell / Close'}
                  </button>
                </Td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SettledTable({
  positions,
  loading,
  onChanged,
}: {
  positions: Position[]
  loading: boolean
  onChanged: () => void
}) {
  const { push } = useToast()
  const [claiming, setClaiming] = useState<string | null>(null)

  async function claim(p: Position) {
    setClaiming(p.position_id)
    try {
      const res = await api.redeemPosition(p.position_id)
      push(
        res.payout_amount > 0
          ? `Payout claimed: $${res.payout_amount.toFixed(2)} credited to your wallet.`
          : 'Losing token claimed — $0.00 settlement recorded.',
        res.payout_amount > 0 ? 'info' : 'info'
      )
      onChanged()
    } catch (err: any) {
      push(err.message || 'Claim failed', 'error')
    } finally {
      setClaiming(null)
    }
  }

  if (loading) return <Skeleton className="h-40 w-full" />
  if (positions.length === 0)
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
        <p className="text-sm font-medium text-slate-300">No settled positions yet</p>
        <p className="mt-1 text-xs text-slate-500">
          Once a market resolves, winning tokens can be redeemed 1:1 for USDC here.
        </p>
      </div>
    )
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <Th>Market</Th>
            <Th>Token</Th>
            <Th right>Shares</Th>
            <Th>Status</Th>
            <Th right>Payout</Th>
            <Th right>Action</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70">
          {positions.map((p) => (
            <tr key={p.position_id} className="hover:bg-slate-900/50">
              <Td className="font-medium text-slate-200">{p.event_title || p.market_question}</Td>
              <Td><TokenChip symbol={p.outcome_symbol || '—'} /></Td>
              <Td right mono>{p.shares.toFixed(1)}</Td>
              <Td>
                {p.claimed ? (
                  <StatusPill status="RESOLVED" />
                ) : (
                  <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                    Claim ready
                  </span>
                )}
              </Td>
              <Td right mono>{p.claimed ? '—' : `$${(p.shares * 1.0).toFixed(2)} max`}</Td>
              <Td right>
                {p.claimed ? (
                  <span className="text-[10px] text-slate-500">Claimed</span>
                ) : (
                  <button
                    disabled={claiming === p.position_id || p.shares <= 0}
                    onClick={() => claim(p)}
                    className="rounded-md bg-emerald-500 px-3 py-1 text-[10px] font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-40"
                  >
                    {claiming === p.position_id ? 'Claiming…' : 'Claim Payout'}
                  </button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OrdersTable({
  orders,
  loading,
  onChanged,
}: {
  orders: Order[]
  loading: boolean
  onChanged: () => void
}) {
  const { push } = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  async function cancel(orderId: string | null) {
    if (!orderId) return
    setBusy(orderId)
    try {
      await api.cancelOrder(orderId)
      push('Order cancelled, locked funds released.', 'info')
      onChanged()
    } catch (err: any) {
      push(err.message || 'Cancel failed', 'error')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <Skeleton className="h-40 w-full" />
  if (orders.length === 0)
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
        <p className="text-sm font-medium text-slate-300">No open orders</p>
        <p className="mt-1 text-xs text-slate-500">Resting limit orders appear here with one-click cancel.</p>
      </div>
    )
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <button
          onClick={async () => {
            try {
              const res = await api.cancelAllOrders({})
              push(`Cancelled ${res.cancelled_count} order(s).`, 'info')
              onChanged()
            } catch (err: any) {
              push(err.message || 'Batch cancel failed', 'error')
            }
          }}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] font-medium text-slate-300 transition hover:border-rose-500/50 hover:text-rose-300"
        >
          Cancel All
        </button>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-slate-800">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <Th>Placed</Th>
              <Th>Market</Th>
              <Th>Side</Th>
              <Th right>Price</Th>
              <Th right>Size</Th>
              <Th right>Filled</Th>
              <Th>Status</Th>
              <Th right>Action</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {orders.map((o) => (
              <tr
                key={o.id}
                className={`hover:bg-slate-900/50 ${
                  o.pending ? 'animate-pulse bg-amber-500/5' : ''
                }`}
              >
                <Td mono>{new Date(o.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</Td>
                <Td className="text-slate-300">{o.token_id.slice(0, 18)}…</Td>
                <Td><TokenChip symbol={o.side} /></Td>
                <Td right mono>¢{(o.price * 100).toFixed(0)}</Td>
                <Td right mono>{o.amount}</Td>
                <Td right mono
                >
                  {((o.filled_amount / Math.max(1, o.amount)) * 100).toFixed(0)}%
                </Td>
                <Td>
                  {o.pending ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                      <span className="h-1.5 w-1.5 animate-ping rounded-full bg-amber-400" />
                      Pending
                    </span>
                  ) : (
                    <StatusPill status={o.status} />
                  )}
                </Td>
                <Td right>
                  <button
                    disabled={busy === o.id || o.pending || !o.id}
                    onClick={() => o.id && cancel(o.id)}
                    className="rounded-md border border-slate-700 px-2.5 py-1 text-[10px] font-medium text-slate-300 transition hover:border-rose-500/50 hover:text-rose-300 disabled:opacity-40"
                  >
                    {busy === o.id ? '…' : 'Cancel'}
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TradesTable({ fills, loading }: { fills: any[] | null; loading: boolean }) {
  if (loading) return <Skeleton className="h-40 w-full" />
  if (!fills || fills.length === 0)
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
        <p className="text-sm font-medium text-slate-300">No fills yet</p>
        <p className="mt-1 text-xs text-slate-500">Matched executions and their fees are recorded here.</p>
      </div>
    )
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <Th>Side</Th>
            <Th right>Price</Th>
            <Th right>Original Size</Th>
            <Th right>Filled</Th>
            <Th>Status</Th>
            <Th right>Placed</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70">
          {fills.map((f) => (
            <tr key={f.id} className="hover:bg-slate-900/50">
              <Td><TokenChip symbol={f.side} /></Td>
              <Td right mono>¢{(f.price * 100).toFixed(0)}</Td>
              <Td right mono>{f.amount}</Td>
              <Td right mono>{f.filled_amount}</Td>
              <Td><StatusPill status={f.status} /></Td>
              <Td right mono>{new Date(f.created_at).toLocaleString()}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LedgerTable({ entries, loading }: { entries: LedgerEntry[] | null; loading: boolean }) {
  if (loading) return <Skeleton className="h-40 w-full" />
  if (!entries || entries.length === 0)
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
        <p className="text-sm font-medium text-slate-300">Ledger empty</p>
        <p className="mt-1 text-xs text-slate-500">Deposits, withdrawals, fees, and payouts all flow through here.</p>
      </div>
    )
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <Th>Time</Th>
            <Th>Kind</Th>
            <Th>Reference</Th>
            <Th right>Amount</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70">
          {entries.map((e) => (
            <tr key={e.id} className="hover:bg-slate-900/50">
              <Td mono>{new Date(e.created_at).toLocaleString()}</Td>
              <Td>
                <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-300">
                  {e.kind}
                </span>
              </Td>
              <Td className="text-slate-500">{e.reference|| '—'}</Td>
              <Td right>
                <span className={`font-mono ${e.amount >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {e.amount >= 0 ? '+' : ''}${e.amount.toFixed(2)}
                </span>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SecurityPanel() {
  const { push } = useToast()
  const [passkeys, setPasskeys] = useState<PasskeyCredentialInfo[] | null>(null)
  const [registering, setRegistering] = useState(false)
  const [revoking, setRevoking] = useState<string | null>(null)

  async function load() {
    try {
      const res = await api.listPasskeys()
      setPasskeys(res.passkeys)
    } catch {
      setPasskeys([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function registerPasskey() {
    setRegistering(true)
    try {
      const options = await api.passkeyRegisterOptions()
      const credential = await startRegistration({
        optionsJSON: options.publicKey,
      })
      await api.passkeyRegisterVerify(credential)
      push('Passkey registered — you can now sign in without a password.', 'info')
      await load()
    } catch (err: any) {
      push(err?.message || 'Passkey registration failed', 'error')
    } finally {
      setRegistering(false)
    }
  }

  async function revoke(credentialId: string) {
    setRevoking(credentialId)
    try {
      await api.deletePasskey(credentialId)
      push('Passkey revoked.', 'info')
      await load()
    } catch (err: any) {
      push(err?.message || 'Could not revoke the passkey', 'error')
    } finally {
      setRevoking(null)
    }
  }

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Fingerprint className="h-4 w-4 text-emerald-400" />
              Passkeys
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Sign in with Face ID, Touch ID, a security key or your device
              PIN — no password required.
            </p>
          </div>
          <button
            onClick={registerPasskey}
            disabled={registering}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-40"
          >
            {registering ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <KeyRound className="h-3.5 w-3.5" />
            )}
            {registering ? 'Waiting…' : 'Add passkey'}
          </button>
        </div>

        <div className="mt-4">
          {passkeys == null ? (
            <Skeleton className="h-20 w-full" />
          ) : passkeys.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 py-8 text-center">
              <p className="text-xs font-medium text-slate-300">No passkeys yet</p>
              <p className="mt-1 text-[11px] text-slate-500">
                Register one to sign in with your device instead of a password.
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {passkeys.map((p) => (
                <li
                  key={p.credential_id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-slate-200">
                      {p.label || 'Passkey'}
                    </p>
                    <p className="text-[10px] text-slate-500">
                      Added {new Date(p.created_at).toLocaleDateString()}
                      {p.last_used_at
                        ? ` · last used ${new Date(p.last_used_at).toLocaleDateString()}`
                        : ''}
                      {` · counter ${p.sign_count}`}
                    </p>
                  </div>
                  <button
                    onClick={() => revoke(p.credential_id)}
                    disabled={revoking === p.credential_id}
                    className="flex shrink-0 items-center gap-1 rounded-md border border-rose-500/40 px-2 py-1 text-[10px] font-medium text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-40"
                  >
                    <Trash2 className="h-3 w-3" />
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
          Account security
        </h3>
        <ul className="mt-3 space-y-2.5 text-xs text-slate-400">
          <li className="flex items-start gap-2">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
            Passwords are hashed with native bcrypt; federated accounts have no
            usable password.
          </li>
          <li className="flex items-start gap-2">
            <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
            Algorithmic traders can rotate an HMAC-signed API key from the API
            and sign every request.
          </li>
          <li className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
            Sign-in and order endpoints are rate limited per IP and credential.
          </li>
        </ul>
      </div>
    </div>
  )
}

function TokenChip({ symbol }: { symbol: string }) {
  const isBuy = symbol === 'BUY'
  const tone = isBuy
    ? 'bg-emerald-500/10 text-emerald-400'
    : symbol === 'SELL'
      ? 'bg-rose-500/10 text-rose-400'
      : 'bg-blue-500/10 text-blue-300'
  return (
    <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${tone}`}>
      {symbol}
    </span>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-4 py-3 ${right ? 'text-right' : ''}`}>{children}</th>
}
function Td({ children, right, mono, className = '' }: { children: React.ReactNode; right?: boolean; mono?: boolean; className?: string }) {
  return (
    <td className={`px-4 py-3 ${right ? 'text-right' : ''} ${mono ? 'font-mono' : ''} ${className}`}>
      {children}
    </td>
  )
}
