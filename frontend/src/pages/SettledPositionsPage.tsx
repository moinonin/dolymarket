import React, { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { Skeleton } from '../components/ui'
import { useToast } from '../context/toast'

export default function SettledPositionsPage() {
  const { user, openAuth } = useAuth()
  const { push } = useToast()
  const [positions, setPositions] = useState<any[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!user) { setLoading(false); return }
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await api.getSettledPositions()
        if (!cancelled) setPositions(res.positions || [])
      } catch (err: any) {
        if (!cancelled) { setError(err?.message || 'Could not load settled positions'); setPositions([]) }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [user])

  if (!user) {
    return (
      <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-12 text-center">
        <p className="text-sm font-medium text-slate-300">Sign in to view settled positions</p>
        <button onClick={() => openAuth('login')} className="mt-4 rounded-lg bg-cyan-500 px-4 py-2 text-xs font-bold text-slate-950 transition hover:bg-cyan-400">
          Sign in
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      <h1 className="text-2xl font-bold text-white">Settled positions</h1>
      <p className="mt-1 text-sm text-slate-400">Resolved positions and payouts.</p>
      {error && <div className="mt-4 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">{error}</div>}
      {loading ? (
        <div className="mt-6 space-y-2">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
        </div>
      ) : (positions || []).length === 0 ? (
        <div className="mt-10 rounded-2xl border border-dashed border-slate-800 py-14 text-center">
          <p className="text-sm font-medium text-slate-300">No settled positions</p>
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-800">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">Market</th>
                <th className="px-3 py-2 text-left">Token</th>
                <th className="px-3 py-2 text-right">Shares</th>
                <th className="px-3 py-2 text-right">Realized PnL</th>
                <th className="px-3 py-2 text-left">Claimed</th>
              </tr>
            </thead>
            <tbody>
              {(positions || []).map((p: any) => (
                <tr key={p.id} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 font-mono text-slate-300">{p.market_id}</td>
                  <td className="px-3 py-2 font-mono text-slate-300">{p.token_id}</td>
                  <td className="px-3 py-2 text-right font-mono">{Number(p.shares).toFixed(4)}</td>
                  <td className="px-3 py-2 text-right font-mono">{Number(p.realized_pnl).toFixed(4)}</td>
                  <td className="px-3 py-2">{p.claimed ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}