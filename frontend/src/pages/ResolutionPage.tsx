import React, { useEffect, useState } from 'react'
import { Gavel, ShieldAlert, Timer } from 'lucide-react'
import { api } from '../api/client'
import { Skeleton, StatusPill } from '../components/ui'
import { useToast } from '../context/toast'

interface ResolutionRow {
  market_id: string
  question: string
  event_title: string | null
  outcomes: string[]
  market_status: string
  dispute_status: string | null
  proposed_outcome_index: number | null
  proposer_address: string | null
  bond_amount: number | null
  dispute_deadline: string | null
}

export default function ResolutionPage() {
  const [rows, setRows] = useState<ResolutionRow[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await api.listResolutionMarkets()
        if (!cancelled) setRows(res.markets)
      } catch {
        if (!cancelled) setRows([])
      }
    }
    load()
    const iv = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(iv)
      setBusy(null)
    }
  }, [])

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      <header className="mb-8">
        <div className="flex items-center gap-2.5">
          <Gavel className="h-5 w-5 text-amber-400" />
          <h1 className="text-2xl font-bold tracking-tight text-white">Resolution & Oracle</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          UMA-style optimistic oracle in simulation: a proposer stakes a bond and asserts the
          winning outcome. During the challenge window, anyone can post a counter-bond to
          dispute. Uncontested assertions finalize automatically.
        </p>
      </header>

      {rows == null ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 py-20 text-center">
          <Gavel className="mx-auto mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm font-medium text-slate-300">No markets in resolution</p>
          <p className="mt-1 text-xs text-slate-500">
            Markets appear here when trading closes and a bonded outcome proposal is live.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {rows.map((r) => (
            <ResolutionCard key={r.market_id} row={r} busy={busy} setBusy={setBusy} />
          ))}
        </div>
      )}
    </div>
  )
}

function ResolutionCard({
  row,
  busy,
  setBusy,
}: {
  row: ResolutionRow
  busy: string | null
  setBusy: (v: string | null) => void
}) {
  const { push } = useToast()
  const deadline = row.dispute_deadline ? new Date(row.dispute_deadline) : null
  const [remaining, setRemaining] = useState<string | null>(null)

  useEffect(() => {
    if (!deadline) return
    function tick() {
      const ms = deadline!.getTime() - Date.now()
      setRemaining(ms > 0 ? `${Math.floor(ms / 60000)}m remaining` : 'window closed')
    }
    tick()
    const iv = setInterval(tick, 1000)
    return () => clearInterval(iv)
  }, [row.dispute_deadline])

  async function dispute() {
    if (setBusy) setBusy(row.market_id)
    try {
      await api.disputeProposal(row.market_id)
      push('Counter-bond posted — market moved to DISPUTED.', 'info')
    } catch (err: any) {
      push(err.message || 'Dispute failed', 'error')
    } finally {
      setBusy(null)
    }
  }

  const proposed = row.proposed_outcome_index

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            {row.event_title || 'Event'}
          </div>
          <h3 className="mt-0.5 font-semibold leading-snug text-white">{row.question}</h3>
        </div>
        <StatusPill status={row.market_status} />
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
          <span className="text-slate-400">Proposed winner</span>
          <span className="font-mono font-semibold text-amber-300">
            {proposed != null ? row.outcomes[proposed] : '—'}{' '}
            <span className="text-slate-600">(index {proposed ?? '—'})</span>
          </span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
          <span className="text-slate-400">Proposer</span>
          <span className="font-mono text-slate-300">{row.proposer_address || '—'}</span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
          <span className="text-slate-400">Bond</span>
          <span className="font-mono text-slate-200">
            {row.bond_amount != null ? `$${row.bond_amount.toFixed(0)} USDC` : '—'}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
          <span className="flex items-center gap-1.5 text-slate-400">
            <Timer className="h-3.5 w-3.5" /> Dispute window
          </span>
          <span className={`font-mono ${row.dispute_status === 'DISPUTED' ? 'text-red-300' : 'text-amber-300'}`}>
            {remaining || '—'}
          </span>
        </div>
      </div>

      {row.dispute_status === 'PROPOSED' && (
        <button
          onClick={dispute}
          disabled={busy === row.market_id}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 py-2.5 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-40"
        >
          <ShieldAlert className="h-4 w-4" />
          {busy === row.market_id ? 'Posting bond…' : 'Stake Counter-Bond & Dispute'}
        </button>
      )}
      {row.dispute_status === 'DISPUTED' && (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-center text-xs text-red-200">
          Disputed — awaiting dispute resolution. Outcome not yet final.
        </div>
      )}
    </div>
  )
}
