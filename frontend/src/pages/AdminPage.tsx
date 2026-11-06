import React, { useCallback, useEffect, useState } from 'react'
import {
  Activity,
  CheckCircle2,
  ClipboardList,
  Gavel,
  Plus,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { api, type AdminCopyJob, type AdminDesk, type Market } from '../api/client'
import { Skeleton } from '../components/ui'
import { useToast } from '../context/toast'

type Tab = 'markets' | 'desks' | 'copy'

const TABS: { key: Tab; label: string; icon: typeof Activity }[] = [
  { key: 'markets', label: 'Markets', icon: Gavel },
  { key: 'desks', label: 'Desk review', icon: ClipboardList },
  { key: 'copy', label: 'Copy activity', icon: Activity },
]

const DESK_STATUSES = ['PENDING_REVIEW', 'ACTIVE', 'SUSPENDED', 'REJECTED', 'ARCHIVED', 'DRAFT']

export default function AdminPage() {
  const { push } = useToast()
  const [tab, setTab] = useState<Tab>('markets')

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      <header className="mb-6">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-400" />
          <h1 className="text-2xl font-bold text-white">Operations console</h1>
        </div>
        <p className="mt-1 text-sm text-slate-400">
          Create markets, review Pro Desks and audit copy activity. Every action here is
          restricted to admin accounts on the server.
        </p>
      </header>

      <div className="mb-6 flex flex-wrap gap-1.5">
        {TABS.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                tab === t.key
                  ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'markets' && <MarketsPanel push={push} />}
      {tab === 'desks' && <DeskReviewPanel push={push} />}
      {tab === 'copy' && <CopyActivityPanel />}
    </div>
  )
}

// ---------------------------------------------------------------- markets ---

function MarketsPanel({ push }: { push: (m: string, k?: 'info' | 'error') => void }) {
  const [markets, setMarkets] = useState<Market[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState<string | null>(null)

  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('Politics')
  const [eventSlug, setEventSlug] = useState('')
  const [question, setQuestion] = useState('')
  const [outcomes, setOutcomes] = useState('Yes, No')
  const [creatingEvent, setCreatingEvent] = useState(false)
  const [creatingMarket, setCreatingMarket] = useState(false)

  const load = useCallback(async () => {
    try {
      setError(null)
      const res = await api.listMarkets({ status: 'ACTIVE' })
      setMarkets(res.markets || [])
    } catch (err: any) {
      setError(err?.message || 'Could not load markets')
      setMarkets([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function createEvent(e: React.FormEvent) {
    e.preventDefault()
    if (!slug.trim() || !title.trim()) return
    setCreatingEvent(true)
    try {
      await api.createEvent({
        slug: slug.trim(),
        title: title.trim(),
        category: category.trim() || 'Politics',
      })
      push(`Event "${slug.trim()}" created.`, 'info')
      setSlug('')
      setTitle('')
      setEventSlug(slug.trim())
    } catch (err: any) {
      push(err?.message || 'Could not create the event', 'error')
    } finally {
      setCreatingEvent(false)
    }
  }

  async function createMarket(e: React.FormEvent) {
    e.preventDefault()
    const parsed = outcomes
      .split(',')
      .map((o) => o.trim())
      .filter(Boolean)
    if (!eventSlug.trim() || !question.trim() || parsed.length < 2) return
    setCreatingMarket(true)
    try {
      await api.createMarket({
        event_slug: eventSlug.trim(),
        question: question.trim(),
        outcomes: parsed,
      })
      push('Market created and live.', 'info')
      setQuestion('')
      await load()
    } catch (err: any) {
      push(err?.message || 'Could not create the market', 'error')
    } finally {
      setCreatingMarket(false)
    }
  }

  async function close(marketId: string) {
    setClosing(marketId)
    try {
      await api.closeMarket(marketId)
      push('Market closed — trading halted.', 'info')
      await load()
    } catch (err: any) {
      push(err?.message || 'Could not close the market', 'error')
    } finally {
      setClosing(null)
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Plus className="h-4 w-4 text-emerald-400" />
          New event
        </h2>
        <form onSubmit={createEvent} className="mt-3 space-y-3">
          <Field label="Slug">
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="election-2026"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <Field label="Title">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Election 2026"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <Field label="Category">
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <button
            type="submit"
            disabled={creatingEvent || !slug.trim() || !title.trim()}
            className="rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {creatingEvent ? 'Creating…' : 'Create event'}
          </button>
        </form>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Plus className="h-4 w-4 text-emerald-400" />
          New market
        </h2>
        <form onSubmit={createMarket} className="mt-3 space-y-3">
          <Field label="Event slug">
            <input
              value={eventSlug}
              onChange={(e) => setEventSlug(e.target.value)}
              placeholder="election-2026"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <Field label="Question">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Will the incumbent win?"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <Field label="Outcomes (comma separated)">
            <input
              value={outcomes}
              onChange={(e) => setOutcomes(e.target.value)}
              placeholder="Yes, No"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/60"
            />
          </Field>
          <button
            type="submit"
            disabled={creatingMarket || !eventSlug.trim() || !question.trim()}
            className="rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {creatingMarket ? 'Creating…' : 'Create market'}
          </button>
        </form>
      </section>

      <section className="lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold text-white">Open markets</h2>
        {error && (
          <div className="mb-3 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
            {error}
          </div>
        )}
        {markets === null ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-xl border border-slate-800/70 p-4">
                <Skeleton className="mb-2 h-3 w-2/3" />
                <Skeleton className="h-2 w-1/3" />
              </div>
            ))}
          </div>
        ) : markets.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-800 py-12 text-center">
            <p className="text-sm font-medium text-slate-300">No open markets</p>
            <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
              Create an event and a market above to open the first tradable market.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {markets.map((m) => (
              <div
                key={m.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{m.question}</p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    {m.outcomes.join(' / ')} · {m.status} · {m.id.slice(0, 8)}
                  </p>
                </div>
                <button
                  onClick={() => void close(m.id)}
                  disabled={closing === m.id}
                  className="rounded-lg border border-rose-800/60 px-2.5 py-1.5 text-[11px] font-medium text-rose-300 transition hover:bg-rose-950/40 disabled:opacity-40"
                >
                  {closing === m.id ? 'Closing…' : 'Close market'}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

// ------------------------------------------------------------- desk review ---

function DeskReviewPanel({
  push,
}: {
  push: (m: string, k?: 'info' | 'error') => void
}) {
  const [desks, setDesks] = useState<AdminDesk[] | null>(null)
  const [status, setStatus] = useState('PENDING_REVIEW')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const res = await api.listAdminDesks(status)
      setDesks(res.desks || [])
    } catch (err: any) {
      setError(err?.message || 'Could not load the review queue')
      setDesks([])
    }
  }, [status])

  useEffect(() => {
    void load()
  }, [load])

  async function act(deskId: string, action: 'approve' | 'reject' | 'suspend') {
    setBusy(`${deskId}:${action}`)
    try {
      if (action === 'approve') await api.approveDesk(deskId)
      else if (action === 'suspend') await api.adminSuspendDesk(deskId)
      else {
        const reason = window.prompt('Reason for rejection') || ''
        if (!reason.trim()) {
          setBusy(null)
          return
        }
        await api.rejectDesk(deskId, reason.trim())
      }
      push(
        action === 'approve'
          ? 'Desk approved — it is now live in the leaderboard.'
          : action === 'suspend'
            ? 'Desk suspended.'
            : 'Desk rejected.',
        action === 'approve' ? 'info' : 'info'
      )
      await load()
    } catch (err: any) {
      push(err?.message || 'The review action failed', 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-white">Desk queue</h2>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
        >
          {DESK_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
          {error}
        </div>
      )}

      {desks === null ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-800/70 p-4">
              <Skeleton className="mb-2 h-3 w-1/3" />
              <Skeleton className="h-2 w-1/2" />
            </div>
          ))}
        </div>
      ) : desks.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 py-12 text-center">
          <p className="text-sm font-medium text-slate-300">Nothing in this queue</p>
          <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
            Desks appear here once their owner submits them for review.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {desks.map((d) => (
            <div
              key={d.id}
              className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-white">{d.name}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  {d.owner_email ?? 'unknown owner'} · {d.follower_count} followers · {d.status}
                </p>
                {d.review_note && (
                  <p className="mt-1 text-[11px] text-amber-300/90">Note: {d.review_note}</p>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => void act(d.id, 'approve')}
                  disabled={busy !== null}
                  className="flex items-center gap-1 rounded-lg border border-emerald-700/60 px-2.5 py-1.5 text-[11px] font-medium text-emerald-300 transition hover:bg-emerald-950/40 disabled:opacity-40"
                >
                  <CheckCircle2 className="h-3 w-3" /> Approve
                </button>
                <button
                  onClick={() => void act(d.id, 'reject')}
                  disabled={busy !== null}
                  className="flex items-center gap-1 rounded-lg border border-rose-800/60 px-2.5 py-1.5 text-[11px] font-medium text-rose-300 transition hover:bg-rose-950/40 disabled:opacity-40"
                >
                  <XCircle className="h-3 w-3" /> Reject
                </button>
                <button
                  onClick={() => void act(d.id, 'suspend')}
                  disabled={busy !== null}
                  className="rounded-lg border border-slate-700 px-2.5 py-1.5 text-[11px] font-medium text-slate-300 transition hover:bg-slate-800 disabled:opacity-40"
                >
                  Suspend
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------- copy activity ---

function CopyActivityPanel() {
  const [jobs, setJobs] = useState<AdminCopyJob[] | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setJobs(null)
    api
      .listAdminCopyJobs({ status: status || undefined, limit: 100 })
      .then((res) => {
        if (!cancelled) setJobs(res.jobs || [])
      })
      .catch((err: any) => {
        if (cancelled) return
        setError(err?.message || 'Could not load copy jobs')
        setJobs([])
      })
    return () => {
      cancelled = true
    }
  }, [status, reload])

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-white">Copy jobs</h2>
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
          >
            <option value="">All statuses</option>
            {['PENDING', 'FILLED', 'REJECTED', 'SKIPPED', 'LIMIT_BREACHED'].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            onClick={() => setReload((n) => n + 1)}
            className="rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
          {error}
        </div>
      )}

      {jobs === null ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-800/70 p-4">
              <Skeleton className="mb-2 h-3 w-1/2" />
              <Skeleton className="h-2 w-1/3" />
            </div>
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 py-12 text-center">
          <p className="text-sm font-medium text-slate-300">No copy jobs yet</p>
          <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
            Copy jobs are created when a desk fills and a follower mirrors it.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-800">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">Desk</th>
                <th className="px-4 py-2.5 font-medium">Follower</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Ratio</th>
                <th className="px-4 py-2.5 font-medium">Shares</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {jobs.map((j) => (
                <tr key={j.id} className="text-slate-300">
                  <td className="px-4 py-2.5">{j.desk_name ?? j.desk_id}</td>
                  <td className="px-4 py-2.5">{j.follower_email ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        j.status === 'FILLED'
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : j.status === 'REJECTED'
                            ? 'bg-rose-500/15 text-rose-300'
                            : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {j.status}
                    </span>
                    {j.error_code && (
                      <span className="ml-1.5 text-[10px] text-slate-500">{j.error_code}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 font-mono">{(j.copy_ratio * 100).toFixed(0)}%</td>
                  <td className="px-4 py-2.5 font-mono">
                    {j.filled_shares}/{j.requested_shares}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{j.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}
