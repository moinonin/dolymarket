import React, { useCallback, useEffect, useState } from 'react'
import { Activity, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { Skeleton } from '../components/ui'

interface CopyJobRow {
  id: string
  desk_id: string
  source_fill_id: string
  status: string
  copy_ratio: number
  requested_shares: number
  filled_shares: number
  limit_breached: boolean
  error_code: string | null
  created_at: string
}

const STATUS_FILTERS = ['', 'PENDING', 'FILLED', 'REJECTED', 'SKIPPED']

export default function CopyActivityPage({ onOpenDesk }: { onOpenDesk: (id: string) => void }) {
  const [jobs, setJobs] = useState<CopyJobRow[] | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const res = await api.listCopyJobs({ status: status || undefined, limit: 100 })
      setJobs((res.jobs || []) as CopyJobRow[])
    } catch (err: any) {
      setError(err?.message || 'Could not load your copy activity')
      setJobs([])
    }
  }, [status])

  useEffect(() => {
    setJobs(null)
    void load()
  }, [load])

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-400" />
            <h1 className="text-2xl font-bold text-white">Copy activity</h1>
          </div>
          <p className="mt-1 text-sm text-slate-400">
            Every order your followers mirrored from a desk, with the size that was requested and
            the size that was filled.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s || 'all'} value={s}>
                {s || 'All statuses'}
              </option>
            ))}
          </select>
          <button
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-3 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">
          {error}
        </div>
      )}

      {jobs === null ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-800/70 p-4">
              <Skeleton className="mb-2 h-3 w-1/3" />
              <Skeleton className="h-2 w-1/2" />
            </div>
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 py-14 text-center">
          <Activity className="mx-auto mb-3 h-7 w-7 text-slate-600" />
          <p className="text-sm font-medium text-slate-300">No copy activity yet</p>
          <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
            Follow a desk and this page fills with the orders the copy engine mirrored for you.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-800">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">Desk</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Ratio</th>
                <th className="px-4 py-2.5 font-medium">Shares</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {jobs.map((j) => (
                <tr key={j.id} className="text-slate-300">
                  <td className="px-4 py-2.5">
                    <button
                      onClick={() => onOpenDesk(j.desk_id)}
                      className="text-emerald-300 underline-offset-2 hover:underline"
                    >
                      {j.desk_id.slice(0, 8)}
                    </button>
                  </td>
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
                    {j.limit_breached && (
                      <span className="ml-1.5 text-[10px] text-amber-300">limit</span>
                    )}
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
    </div>
  )
}
