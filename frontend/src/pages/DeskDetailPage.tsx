import React, { useEffect, useState } from 'react'
import { ArrowLeft, Loader2, ShieldCheck, TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { useToast } from '../context/toast'
import { Skeleton } from '../components/ui'

export default function DeskDetailPage({
  deskId,
  onBack,
}: {
  deskId: string
  onBack: () => void
}) {
  const { user, openAuth } = useAuth()
  const { push } = useToast()
  const [desk, setDesk] = useState<any>(null)
  const [record, setRecord] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ratio, setRatio] = useState('0.25')
  const [acting, setActing] = useState(false)

  async function load() {
    try {
      setLoading(true)
      setError(null)
      const [d, t] = await Promise.all([
        api.getDesk(deskId),
        api.getDeskTrackRecord(deskId),
      ])
      setDesk(d.desk)
      setRecord(t.track_record)
    } catch (err: any) {
      setError(err?.message || 'Could not load desk')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [deskId])

  const isOwner = user && desk && desk.owner_user_id === user.id

  async function follow() {
    setActing(true)
    try {
      await api.followDesk(deskId, { copy_ratio: Number(ratio) })
      push('Now following this desk.', 'info')
    } catch (err: any) {
      push(err?.message || 'Could not follow', 'error')
    } finally {
      setActing(false)
    }
  }

  async function submit() {
    setActing(true)
    try {
      await api.submitDesk(deskId)
      push('Submitted for review.', 'info')
      await load()
    } catch (err: any) {
      push(err?.message || 'Could not submit', 'error')
    } finally {
      setActing(false)
    }
  }

  async function archive() {
    if (!window.confirm('Archive this desk? This cannot be undone.')) return
    setActing(true)
    try {
      await api.archiveDesk(deskId)
      push('Desk archived.', 'info')
      await load()
    } catch (err: any) {
      push(err?.message || 'Could not archive', 'error')
    } finally {
      setActing(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-xs text-slate-400 transition hover:text-slate-200"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to desks
      </button>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : desk ? (
        <>
          <h1 className="text-2xl font-bold text-white">{desk.name}</h1>
          {desk.description && <p className="mt-1 text-sm text-slate-400">{desk.description}</p>}
          <div className="mt-2">
            <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
              {desk.status}
            </span>
          </div>

          <section className="mt-6 grid gap-3 sm:grid-cols-4">
            <Stat label="ROI" value={`${(record?.roi_pct ?? 0).toFixed(2)}%`} />
            <Stat label="Win rate" value={`${((record?.win_rate ?? 0) * 100).toFixed(0)}%`} />
            <Stat label="Net PnL" value={`$${(record?.net_pnl_usdc ?? 0).toFixed(2)}`} />
            <Stat label="Max DD" value={`${(record?.max_drawdown_pct ?? 0).toFixed(2)}%`} />
          </section>

          <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              Track record
            </h2>
            <p className="mt-1 text-[10px] text-slate-500">
              {record?.closed_positions ?? 0} closed positions · {record?.winning_positions ?? 0} wins ·
              fees paid ${Number(record?.fees_paid_usdc ?? 0).toFixed(2)}
            </p>
            <p className="mt-3 text-[10px] text-slate-600">
              Past results, not indicative of future results.
            </p>
          </section>

          {!user ? (
            <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5 text-center">
              <p className="text-sm text-slate-300">Sign in to follow this desk.</p>
              <button
                onClick={() => openAuth('login')}
                className="mt-3 rounded-lg bg-emerald-500 px-4 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400"
              >
                Sign in
              </button>
            </section>
          ) : isOwner ? (
            <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <ShieldCheck className="h-4 w-4 text-emerald-400" />
                Manage desk
              </h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {desk.status === 'DRAFT' || desk.status === 'REJECTED' ? (
                  <button
                    onClick={submit}
                    disabled={acting}
                    className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-40"
                  >
                    {acting ? 'Working…' : 'Submit for review'}
                  </button>
                ) : null}
                {desk.status === 'ACTIVE' && (
                  <button
                    onClick={async () => {
                      setActing(true)
                      try { await api.suspendDesk(deskId); push('Suspended.', 'info'); await load() }
                      catch (e: any) { push(e?.message || 'Failed', 'error') }
                      finally { setActing(false) }
                    }}
                    disabled={acting}
                    className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs font-medium text-amber-300 transition hover:bg-amber-500/10 disabled:opacity-40"
                  >
                    Suspend
                  </button>
                )}
                {desk.status !== 'ARCHIVED' && (
                  <button
                    onClick={archive}
                    disabled={acting}
                    className="rounded-lg border border-rose-500/40 px-3 py-1.5 text-xs font-medium text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-40"
                  >
                    Archive
                  </button>
                )}
              </div>
              {desk.review_note && (
                <p className="mt-3 text-xs text-amber-300">Review note: {desk.review_note}</p>
              )}
            </section>
          ) : (
            <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="text-sm font-semibold text-white">Follow this desk</h2>
              <p className="mt-1 text-xs text-slate-500">
                Mirror fills proportionally into your own account.
              </p>
              <div className="mt-3 flex items-center gap-2">
                <label className="text-xs text-slate-400">Copy ratio</label>
                <input
                  value={ratio}
                  onChange={(e) => setRatio(e.target.value)}
                  className="w-20 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                />
                <button
                  onClick={follow}
                  disabled={acting}
                  className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-40"
                >
                  {acting ? 'Working…' : 'Follow desk'}
                </button>
              </div>
            </section>
          )}
        </>
      ) : null}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold text-white">{value}</div>
    </div>
  )
}