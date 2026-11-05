import React, { useEffect, useState } from 'react'
import { Activity, Loader2, ShieldCheck, TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import { Skeleton, StatusPill } from '../components/ui'
import { useAuth } from '../auth/AuthProvider'
import { useToast } from '../context/toast'

interface DeskRow {
  id: string
  name: string
  slug: string
  description: string | null
  active_follower_count: number
  copied_fill_count: number
  closed_positions: number
  win_rate: number
  roi_pct: number
  net_pnl_usdc: number
  max_drawdown_pct: number
  created_at: string
}

export default function DesksPage({ onOpenDesk }: { onOpenDesk: (id: string) => void }) {
  const { user, openAuth } = useAuth()
  const { push } = useToast()
  const [desks, setDesks] = useState<DeskRow[] | null>(null)
  const [sort, setSort] = useState('roi_pct')
  const [error, setError] = useState<string | null>(null)
  const [myDesk, setMyDesk] = useState<any>(null)
  const [creating, setCreating] = useState(false)
  const fetchedMyDesk = React.useRef(false)

  async function load() {
    try {
      setError(null)
      const res = await api.listDesks({ sort, limit: 100 })
      setDesks(res.desks as DeskRow[])
    } catch (err: any) {
      setError(err?.message || 'Could not load desks')
      setDesks([])
    }
  }

  useEffect(() => {
    load()
  }, [sort])

  useEffect(() => {
    if (!user) { setMyDesk(null); fetchedMyDesk.current = false; return }
    if (fetchedMyDesk.current) return
    fetchedMyDesk.current = true
    api.getMyDesk().then((r) => setMyDesk(r.desk)).catch(() => setMyDesk(null))
  }, [user])

  async function createDesk() {
    if (!user) { openAuth('register'); return }
    const name = window.prompt('Desk name')
    if (!name) return
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    setCreating(true)
    try {
      await api.createDesk({ name, slug })
      push('Desk created. Add fills, then submit it for review.', 'info')
      const r = await api.getMyDesk()
      setMyDesk(r.desk)
    } catch (err: any) {
      push(err?.message || 'Could not create desk', 'error')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24">
      <section className="pt-10">
        <h1 className="text-2xl font-bold text-white">Live desks</h1>
        <p className="mt-1 text-sm text-slate-400">
          Follow a desk and mirror its fills proportionally into your own
          account. Past results, not indicative of future results.
        </p>
      </section>

      {user && (
        <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <ShieldCheck className="h-4 w-4 text-cyan-400" />
            Your desk
          </h2>
          {myDesk ? (
            <div className="mt-2 text-xs text-slate-400">
              <span className="font-medium text-slate-200">{myDesk.name}</span>{' '}
              <StatusPill status={myDesk.status} /> — {myDesk.track_record?.closed_positions ?? 0} closed
              positions, ROI {(myDesk.track_record?.roi_pct ?? 0).toFixed(2)}%.
              <button
                onClick={() => onOpenDesk(myDesk.id)}
                className="ml-3 text-cyan-400 underline underline-offset-2"
              >
                Open
              </button>
            </div>
          ) : (
            <button
              onClick={createDesk}
              disabled={creating}
              className="mt-3 rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40"
            >
              {creating ? 'Creating…' : 'Create a desk'}
            </button>
          )}
        </section>
      )}

      <section className="mt-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <TrendingUp className="h-4 w-4 text-cyan-400" />
            Leaderboard
          </h2>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
          >
            <option value="roi_pct">ROI</option>
            <option value="net_pnl_usdc">Net PnL</option>
            <option value="active_follower_count">Followers</option>
            <option value="created_at">Newest</option>
          </select>
        </div>

        {error && (
          <div className="mb-3 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
            {error}
          </div>
        )}

        {desks === null ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-2xl border border-slate-800/70 p-5">
                <Skeleton className="mb-3 h-3 w-20" />
                <Skeleton className="mb-5 h-5 w-full" />
                <Skeleton className="h-2 w-2/3" />
              </div>
            ))}
          </div>
        ) : desks.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-800 py-14 text-center">
            <Activity className="mx-auto mb-3 h-7 w-7 text-slate-600" />
            <p className="text-sm font-medium text-slate-300">No desks are live yet</p>
            <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
              Desks appear here once an operator's track record is reviewed and
              approved.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {desks.map((d) => (
              <button
                key={d.id}
                onClick={() => onOpenDesk(d.id)}
                className="group flex flex-col rounded-2xl border border-slate-800 bg-slate-900/60 p-5 text-left transition hover:border-cyan-500/40 hover:bg-slate-900"
              >
                <h3 className="text-sm font-semibold text-white transition group-hover:text-cyan-300">
                  {d.name}
                </h3>
                {d.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">{d.description}</p>
                )}
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">ROI</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-cyan-400">
                      {d.roi_pct.toFixed(2)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">Win</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-white">
                      {(d.win_rate * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">Followers</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-white">
                      {d.active_follower_count}
                    </div>
                  </div>
                </div>
                <div className="mt-3 text-[10px] font-medium text-slate-500">
                  {d.closed_positions} closed positions · max DD {d.max_drawdown_pct.toFixed(2)}%
                </div>
                <div className="mt-2 text-[10px] text-slate-600">
                  Past results, not indicative of future results.
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}