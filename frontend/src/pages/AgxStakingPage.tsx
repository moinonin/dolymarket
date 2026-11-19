import React, { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Clock,
  Coins,
  Gift,
  Loader2,
  Lock,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Unlock,
} from 'lucide-react'
import {
  api,
  type AgxBalance,
  type AgxCooldown,
  type AgxRewardEntry,
  type AgxRewardEpoch,
  type AgxStake,
  type AgxStats,
  type AgxTier,
  type AgxTiersResponse,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { useToast } from '../context/toast'
import { bustSwr, readSwr, writeSwr } from '../api/swrCache'
import { Skeleton, StatusPill } from '../components/ui'

interface WalletState {
  balance: AgxBalance
  stakes: AgxStake[]
  cooldowns: AgxCooldown[]
  rewards: AgxRewardEntry[]
  rewardTotal: string
}

const TIER_STYLES: Record<string, string> = {
  '0': 'border-slate-700 bg-slate-800/60 text-slate-300',
  '1': 'border-amber-600/40 bg-amber-500/10 text-amber-300',
  '2': 'border-slate-400/40 bg-slate-300/10 text-slate-200',
  '3': 'border-yellow-400/50 bg-yellow-400/10 text-yellow-300',
}

/** Trim a decimal-string amount for display only (never for arithmetic). */
function fmtAgx(value: string | null | undefined, maxFrac = 4): string {
  if (!value) return '0'
  const [whole, frac = ''] = value.split('.')
  const trimmed = frac.replace(/0+$/, '')
  const shown = trimmed.slice(0, maxFrac).replace(/0+$/, '')
  return shown ? `${whole}.${shown}` : whole
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

function fmtCountdown(target: string, now: number): string {
  const end = new Date(target).getTime()
  if (!Number.isFinite(end)) return '—'
  const ms = end - now
  if (ms <= 0) return 'Matured'
  const totalMinutes = Math.floor(ms / 60_000)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function cooldownPct(cooldown: AgxCooldown, now: number): number {
  const start = cooldown.created_at ? new Date(cooldown.created_at).getTime() : NaN
  const end = new Date(cooldown.cooldown_until).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 100
  return Math.max(0, Math.min(100, ((now - start) / (end - start)) * 100))
}

export default function AgxStakingPage() {
  const { user, openAuth } = useAuth()
  const { push } = useToast()

  const cachedPub = readSwr<{ tiers: AgxTiersResponse; stats: AgxStats; epochs: AgxRewardEpoch[] }>('agx:public')
  const cachedWallet = user ? readSwr<WalletState>(`agx:wallet:${user.id}`, 2 * 60 * 1000) : null

  const [wallet, setWallet] = useState<WalletState | null>(cachedWallet?.data ?? null)
  const [tiers, setTiers] = useState<AgxTiersResponse | null>(cachedPub?.data.tiers ?? null)
  const [stats, setStats] = useState<AgxStats | null>(cachedPub?.data.stats ?? null)
  const [epochs, setEpochs] = useState<AgxRewardEpoch[]>(cachedPub?.data.epochs ?? [])
  const [loading, setLoading] = useState(!cachedPub)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const load = useCallback(async () => {
    const pubHit = readSwr<{ tiers: AgxTiersResponse; stats: AgxStats; epochs: AgxRewardEpoch[] }>('agx:public')
    if (!pubHit) setLoading(true)
    setError(null)
    try {
      const pubPromise = Promise.all([
        api.getAgxTiers(),
        api.getAgxStats(),
        api.getAgxEpochs(20),
      ])
      const walletPromise = user
        ? Promise.all([
            api.getAgxBalance(),
            api.getAgxStakes(),
            api.getAgxRewardHistory(),
          ])
        : Promise.resolve(null)

      const [[tiersRes, statsRes, epochsRes], walletRes] = await Promise.all([
        pubPromise,
        walletPromise,
      ])
      setTiers(tiersRes)
      setStats(statsRes)
      setEpochs(epochsRes.epochs)
      writeSwr('agx:public', { tiers: tiersRes, stats: statsRes, epochs: epochsRes.epochs })

      if (user && walletRes) {
        const [balance, stakesRes, history] = walletRes
        const nextWallet: WalletState = {
          balance,
          stakes: stakesRes.stakes,
          cooldowns: stakesRes.cooldowns,
          rewards: history.rewards,
          rewardTotal: history.total,
        }
        setWallet(nextWallet)
        writeSwr(`agx:wallet:${user.id}`, nextWallet)
      } else {
        setWallet(null)
      }
    } catch (err: any) {
      if (!pubHit) setError(err?.message || 'Could not load AGX data')
    } finally {
      setLoading(false)
    }
  }, [user?.id])

  useEffect(() => {
    load()
  }, [load])

  async function run(key: string, fn: () => Promise<unknown>, success: string) {
    setBusy(key)
    try {
      await fn()
      bustSwr('agx:')
      push(success, 'info')
      await load()
    } catch {
      // The API client already surfaced the error toast.
    } finally {
      setBusy(null)
    }
  }

  const balance = wallet?.balance
  const amountTrimmed = amount.trim()
  const amountValid =
    /^\d+(\.\d{1,18})?$/.test(amountTrimmed) && Number(amountTrimmed) > 0
  const pendingRewards = Number(balance?.pending_rewards ?? 0)
  const activeStakes = (wallet?.stakes ?? []).filter((s) => s.status === 'ACTIVE')
  const pendingCooldowns = (wallet?.cooldowns ?? []).filter(
    (c) => c.status === 'PENDING'
  )

  return (
    <div className="mx-auto w-full max-w-[1840px] px-4 sm:px-6 lg:px-8 2xl:px-12 pb-24 pt-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-white">
            <Coins className="h-5 w-5 text-amber-400" />
            AGX Staking
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Stake AGX to unlock tiered taker-fee discounts, earn a share of trading
            fees, and bond oracle disputes. AGX is optional — every USDC trading,
            collateral and settlement path works exactly the same without it.
          </p>
        </div>
        <button
          onClick={() => load()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:opacity-40"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">AGX data unavailable</p>
            <p className="mt-0.5 text-rose-300/80">{error}</p>
          </div>
          <button
            onClick={() => load()}
            className="rounded-md border border-rose-500/40 px-2 py-1 text-[11px] font-medium transition hover:bg-rose-500/20"
          >
            Retry
          </button>
        </div>
      )}

      {/* Protocol stats */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Lock className="h-4 w-4 text-amber-400" />}
          label="Total staked"
          value={stats ? `${fmtAgx(stats.total_staked)} AGX` : null}
        />
        <StatCard
          icon={<ShieldCheck className="h-4 w-4 text-emerald-400" />}
          label="Stakers"
          value={stats ? String(stats.staker_count) : null}
        />
        <StatCard
          icon={<Gift className="h-4 w-4 text-blue-400" />}
          label="Distributed to stakers"
          value={stats ? `${fmtAgx(stats.distributed_staker_pool)} AGX` : null}
        />
        <StatCard
          icon={<TrendingUp className="h-4 w-4 text-slate-300" />}
          label="Reward epochs"
          value={stats ? String(stats.epoch_count) : null}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          {/* Caller wallet */}
          {user ? (
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Your AGX</h2>
                {balance && (
                  <span
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${
                      TIER_STYLES[balance.tier] ?? TIER_STYLES['0']
                    }`}
                  >
                    {balance.tier_name} · Tier {balance.tier}
                  </span>
                )}
              </div>

              {loading && !wallet ? (
                <div className="mt-4 space-y-2">
                  <Skeleton className="h-8 w-32" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              ) : balance ? (
                <>
                  <p className="mt-3 font-mono text-2xl font-bold text-white">
                    {fmtAgx(balance.balance)}
                    <span className="ml-1.5 text-xs font-medium text-slate-500">AGX</span>
                  </p>
                  <p className="text-[11px] text-slate-500">Spendable balance</p>

                  <dl className="mt-4 space-y-2 text-xs">
                    <Row label="Staked" value={`${fmtAgx(balance.staked_balance)} AGX`} />
                    <Row
                      label="Gating bonds"
                      value={`${fmtAgx(balance.locked_gating_balance)} AGX`}
                    />
                    <Row
                      label="Dispute bonds"
                      value={`${fmtAgx(balance.locked_dispute_balance)} AGX`}
                    />
                    <Row
                      label="Pending rewards"
                      value={`${fmtAgx(balance.pending_rewards)} AGX`}
                      tone={pendingRewards > 0 ? 'up' : undefined}
                    />
                    <Row
                      label="Taker fee discount"
                      value={`${(Number(balance.discount_rate) * 100).toFixed(1)}%`}
                    />
                  </dl>

                  {pendingRewards > 0 && (
                    <button
                      onClick={() =>
                        run(
                          'claim',
                          () => api.claimAgxRewards(),
                          'Rewards moved to your spendable balance'
                        )
                      }
                      disabled={busy === 'claim'}
                      className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-500 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                    >
                      {busy === 'claim' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      Claim AGX rewards
                    </button>
                  )}
                </>
              ) : (
                <p className="mt-3 text-xs text-slate-500">
                  No AGX activity yet. Stake below to join a tier.
                </p>
              )}
            </section>
          ) : (
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <Coins className="h-4 w-4 text-amber-400" /> AGX tiers are open
              </h2>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">
                Sign in to see your AGX balance, stake tokens and claim fee rewards.
                The tier ladder and protocol stats below are public.
              </p>
              <button
                onClick={() => openAuth('login')}
                className="mt-4 w-full rounded-lg bg-emerald-500 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400"
              >
                Sign in to stake
              </button>
            </section>
          )}

          {/* Stake form */}
          {user && (
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <ArrowUpFromLine className="h-4 w-4 text-amber-400" /> Stake AGX
              </h2>
              <p className="mt-1 text-[11px] text-slate-500">
                New stakes lock for 7 days. Unstaking then enters a 3-day cooldown.
              </p>
              <label className="mt-3 block">
                <span className="text-[11px] font-medium text-slate-400">Amount (AGX)</span>
                <input
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="100"
                  inputMode="decimal"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm outline-none transition focus:border-emerald-500"
                />
              </label>
              {amountTrimmed !== '' && !amountValid && (
                <p className="mt-1 text-[11px] text-amber-400">
                  Enter a positive decimal amount with up to 18 places.
                </p>
              )}
              <button
                onClick={() =>
                  run(
                    'stake',
                    () => api.stakeAgx(amountTrimmed),
                    `Staked ${amountTrimmed} AGX`
                  )
                }
                disabled={!amountValid || busy === 'stake'}
                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg bg-amber-500 py-2 text-xs font-bold text-slate-950 transition hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy === 'stake' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ArrowUpFromLine className="h-3.5 w-3.5" />
                )}
                Stake
              </button>
              <p className="mt-2 text-[10px] text-slate-600">
                Stake from your spendable balance; a 5% discount begins at 100 AGX.
              </p>
            </section>
          )}

          {/* Tier ladder */}
          <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <TrendingUp className="h-4 w-4 text-emerald-400" /> Fee tier ladder
            </h2>
            <div className="mt-3 divide-y divide-slate-800/70">
              {tiers ? (
                tiers.tiers.map((tier: AgxTier) => {
                  const current = balance?.tier === tier.tier
                  return (
                    <div
                      key={tier.tier}
                      className={`flex items-center justify-between py-2 text-xs ${
                        current ? 'text-white' : 'text-slate-400'
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                            TIER_STYLES[tier.tier] ?? TIER_STYLES['0']
                          }`}
                        >
                          {tier.name}
                        </span>
                        {tier.tier !== '0'
                          ? `≥ ${fmtAgx(tier.min_staked, 0)} AGX`
                          : 'No stake'}
                      </span>
                      <span className="font-mono">
                        {(Number(tier.discount_rate) * 100).toFixed(1)}% off
                      </span>
                    </div>
                  )
                })
              ) : (
                <div className="space-y-2 py-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                  <Skeleton className="h-4 w-4/6" />
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="space-y-4 lg:col-span-2">
          {/* Stakes and cooldowns */}
          <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Lock className="h-4 w-4 text-amber-400" /> Stakes &amp; cooldowns
            </h2>

            {!user ? (
              <p className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-4 text-xs text-slate-500">
                Sign in to view your stakes.
              </p>
            ) : loading && !wallet ? (
              <div className="mt-3 space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : activeStakes.length === 0 && pendingCooldowns.length === 0 ? (
              <div className="mt-3 rounded-lg border border-dashed border-slate-700 px-3 py-6 text-center">
                <Unlock className="mx-auto h-5 w-5 text-slate-600" />
                <p className="mt-2 text-xs text-slate-400">No active stakes.</p>
                <p className="mt-1 text-[11px] text-slate-600">
                  Stake AGX above to unlock a taker-fee discount and fee rewards.
                </p>
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {activeStakes.map((stake) => {
                  const matured = new Date(stake.locked_until).getTime() <= now
                  return (
                    <div
                      key={stake.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2.5"
                    >
                      <div>
                        <p className="font-mono text-sm text-white">
                          {fmtAgx(stake.amount)} AGX
                        </p>
                        <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500">
                          <Clock className="h-3 w-3" />
                          {matured
                            ? 'Unlock complete'
                            : `Locked · ${fmtCountdown(stake.locked_until, now)}`}
                          <span className="text-slate-700">·</span>
                          {fmtDate(stake.locked_until)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusPill status={stake.status} />
                        <button
                          onClick={() =>
                            run(
                              `unstake:${stake.id}`,
                              () => api.unstakeAgx(stake.id),
                              'Unstake cooldown started'
                            )
                          }
                          disabled={!matured || busy === `unstake:${stake.id}`}
                          className="flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition hover:border-amber-500/40 hover:text-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {busy === `unstake:${stake.id}` ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <ArrowDownToLine className="h-3 w-3" />
                          )}
                          Unstake
                        </button>
                      </div>
                    </div>
                  )
                })}

                {pendingCooldowns.map((cooldown) => {
                  const matured = new Date(cooldown.cooldown_until).getTime() <= now
                  return (
                    <div
                      key={cooldown.id}
                      className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2.5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="font-mono text-sm text-white">
                            {fmtAgx(cooldown.amount)} AGX
                          </p>
                          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500">
                            <Clock className="h-3 w-3" />
                            {matured
                              ? 'Cooldown complete'
                              : `Cooldown · ${fmtCountdown(cooldown.cooldown_until, now)} remaining`}
                          </p>
                        </div>
                        <button
                          onClick={() =>
                            run(
                              `withdraw:${cooldown.id}`,
                              () => api.withdrawAgx(cooldown.id),
                              'AGX returned to spendable balance'
                            )
                          }
                          disabled={!matured || busy === `withdraw:${cooldown.id}`}
                          className="flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {busy === `withdraw:${cooldown.id}` ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <ArrowDownToLine className="h-3 w-3" />
                          )}
                          Withdraw
                        </button>
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className={`h-full rounded-full transition-all ${
                            matured ? 'bg-emerald-500' : 'bg-amber-500'
                          }`}
                          style={{ width: `${cooldownPct(cooldown, now)}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {/* Reward history */}
          <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <Gift className="h-4 w-4 text-blue-400" /> Fee rewards
              </h2>
              {wallet && (
                <span className="font-mono text-xs text-emerald-400">
                  {fmtAgx(wallet.rewardTotal)} AGX claimed
                </span>
              )}
            </div>
            {!user ? (
              <p className="mt-3 text-xs text-slate-500">
                Sign in to see the fee rewards you have claimed.
              </p>
            ) : loading && !wallet ? (
              <div className="mt-3 space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : !wallet || wallet.rewards.length === 0 ? (
              <div className="mt-3 rounded-lg border border-dashed border-slate-700 px-3 py-6 text-center">
                <Gift className="mx-auto h-5 w-5 text-slate-600" />
                <p className="mt-2 text-xs text-slate-400">No rewards claimed yet.</p>
                <p className="mt-1 text-[11px] text-slate-600">
                  Stakers earn a proportional share of each epoch&apos;s trading fees.
                </p>
              </div>
            ) : (
              <div className="mt-3 divide-y divide-slate-800/70">
                {wallet.rewards.map((reward) => (
                  <div
                    key={reward.id}
                    className="flex items-center justify-between py-2 text-xs"
                  >
                    <div>
                      <p className="font-mono text-white">
                        +{fmtAgx(reward.amount)} AGX
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {reward.reference_id || 'fee reward'} · {fmtDate(reward.created_at)}
                      </p>
                    </div>
                    <span className="font-mono text-[11px] text-slate-400">
                      balance {fmtAgx(reward.balance_after)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Epochs */}
          <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Clock className="h-4 w-4 text-slate-300" /> Reward epochs
            </h2>
            {loading && epochs.length === 0 ? (
              <div className="mt-3 space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : epochs.length === 0 ? (
              <p className="mt-3 rounded-lg border border-dashed border-slate-700 px-3 py-6 text-center text-xs text-slate-500">
                No epochs have been distributed yet.
              </p>
            ) : (
              <div className="mt-3 divide-y divide-slate-800/70">
                {epochs.map((epoch) => (
                  <div
                    key={epoch.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs"
                  >
                    <div>
                      <p className="font-semibold text-white">
                        Epoch #{epoch.epoch_number}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {fmtAgx(epoch.total_fees_collected)} AGX fees ·{' '}
                        {fmtAgx(epoch.total_staked_supply)} AGX staked
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-emerald-400">
                        {fmtAgx(epoch.reward_per_token)} AGX / staked AGX
                      </p>
                      <p className="text-[11px] text-slate-500">
                        staker pool {fmtAgx(epoch.staker_pool)} · creator{' '}
                        {fmtAgx(epoch.creator_share)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string | null
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
        {icon}
        {label}
      </div>
      {value == null ? (
        <Skeleton className="mt-2 h-6 w-24" />
      ) : (
        <p className="mt-1 text-lg font-semibold text-white">{value}</p>
      )}
    </div>
  )
}

function Row({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'up' | 'down'
}) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd
        className={`font-mono ${
          tone === 'up' ? 'text-emerald-400' : 'text-slate-200'
        }`}
      >
        {value}
      </dd>
    </div>
  )
}
