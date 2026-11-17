import React, { useCallback, useEffect, useState } from 'react'
import { Activity, Loader2, Play, ShieldAlert, Square } from 'lucide-react'
import { api, type Market } from '../api/client'
import { useToast } from '../context/toast'

export default function DeskMarketMakerPanel({ deskId }: { deskId: string }) {
  const { push } = useToast()
  const [status, setStatus] = useState<any>(null)
  const [markets, setMarkets] = useState<Market[]>([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [marketId, setMarketId] = useState('')
  const [tokenId, setTokenId] = useState('')
  const [halfSpread, setHalfSpread] = useState('0.02')
  const [quoteSize, setQuoteSize] = useState('10')
  const [maxInventory, setMaxInventory] = useState('100')
  const [cryptoSkew, setCryptoSkew] = useState(true)
  const [dryRun, setDryRun] = useState(true)

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.getDeskMarketMakerStatus(deskId)
      setStatus(s)
      if (s?.market_id && !marketId) setMarketId(s.market_id)
      if (s?.token_id && !tokenId) setTokenId(s.token_id)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [deskId, marketId, tokenId])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  useEffect(() => {
    api
      .listMarkets({ status: 'ACTIVE' })
      .then((res) => {
        const list = res.markets || []
        setMarkets(list)
        if (!marketId && list[0]?.id) {
          setMarketId(list[0].id)
          if (!tokenId && list[0].tokens?.[0]?.token_id) {
            setTokenId(list[0].tokens[0].token_id)
          }
        }
      })
      .catch(() => {
        /* manual input fallback still works */
      })
  }, [])

  useEffect(() => {
    if (!status?.running) return
    const iv = window.setInterval(() => void refreshStatus(), 3000)
    return () => window.clearInterval(iv)
  }, [status?.running, refreshStatus])

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!marketId.trim() || !tokenId.trim()) {
      push('Enter market_id and token_id to start quoting.', 'error')
      return
    }
    setActing(true)
    try {
      const s = await api.startDeskMarketMaker(deskId, {
        market_id: marketId.trim(),
        token_id: tokenId.trim(),
        base_half_spread: halfSpread,
        quote_size: quoteSize,
        max_inventory: maxInventory,
        crypto_skew: cryptoSkew,
        dry_run: dryRun,
      })
      setStatus(s)
      push(`Market maker started (${dryRun ? 'dry-run' : 'live CLOB'})`, 'info')
    } catch (err: any) {
      push(err?.message || 'Could not start market maker', 'error')
    } finally {
      setActing(false)
    }
  }

  const handleStop = async () => {
    setActing(true)
    try {
      const s = await api.stopDeskMarketMaker(deskId)
      setStatus(s)
      push('Market maker stopped', 'info')
    } catch (err: any) {
      push(err?.message || 'Could not stop market maker', 'error')
    } finally {
      setActing(false)
    }
  }

  const dec = status?.last_decision

  return (
    <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Activity className="h-4 w-4 text-emerald-400" />
          Fear &amp; Greed Market Maker
        </h2>
        <div className="flex items-center gap-2">
          {status?.halted && (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-950/60 px-2.5 py-0.5 text-[10px] font-mono text-amber-300">
              <ShieldAlert className="h-3 w-3" /> EWI HALTED
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-mono font-semibold ${
              status?.running
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                : 'bg-slate-800 text-slate-400'
            }`}
          >
            {loading ? 'LOADING' : status?.running ? (status.dry_run ? 'RUNNING (DRY RUN)' : 'RUNNING (LIVE)') : 'STOPPED'}
          </span>
        </div>
      </div>

      {dec && (
        <div className="mt-4 grid gap-2 sm:grid-cols-5">
          <Metric label="Regime / EWI" value={`${dec.regime_state} · ${Number(dec.ewi).toFixed(3)}`} />
          <Metric label="F&amp;G Score" value={`${Number(dec.score_0_100).toFixed(1)}`} />
          <Metric label="Fair Value" value={`$${Number(dec.fair_value).toFixed(3)}`} />
          <Metric
            label="Bid / Ask"
            value={`${dec.bid_price ? `$${dec.bid_price}` : '—'} / ${dec.ask_price ? `$${dec.ask_price}` : '—'}`}
          />
          <Metric
            label="Ticks / Orders"
            value={`${status.ticks ?? 0} · ${status.orders_placed ?? 0}/${status.orders_cancelled ?? 0}`}
          />
        </div>
      )}

      {status?.last_error && (
        <div className="mt-3 rounded-xl border border-rose-800/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
          {status.last_error}
        </div>
      )}

      <form onSubmit={handleStart} className="mt-4 grid gap-3 sm:grid-cols-5">
        {markets.length > 0 && (
          <select
            value={`${marketId}::${tokenId}`}
            onChange={(e) => {
              const [mId, tId] = e.target.value.split('::')
              if (mId) setMarketId(mId)
              if (tId) setTokenId(tId)
            }}
            className="sm:col-span-5 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500/50"
          >
            {markets.flatMap((m) =>
              (m.tokens || []).map((t) => (
                <option key={`${m.id}::${t.token_id}`} value={`${m.id}::${t.token_id}`}>
                  {m.question} — {t.symbol}
                </option>
              ))
            )}
          </select>
        )}
        <input
          value={marketId}
          onChange={(e) => setMarketId(e.target.value)}
          placeholder="market_id"
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500/50"
        />
        <input
          value={tokenId}
          onChange={(e) => setTokenId(e.target.value)}
          placeholder="token_id"
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500/50"
        />
        <input
          value={halfSpread}
          onChange={(e) => setHalfSpread(e.target.value)}
          placeholder="Half spread (0.02)"
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500/50"
        />
        <input
          value={quoteSize}
          onChange={(e) => setQuoteSize(e.target.value)}
          placeholder="Quote size (10)"
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500/50"
        />
        <input
          value={maxInventory}
          onChange={(e) => setMaxInventory(e.target.value)}
          placeholder="Max inv (100)"
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500/50"
        />

        <div className="flex flex-wrap items-center gap-4 sm:col-span-5">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={cryptoSkew} onChange={(e) => setCryptoSkew(e.target.checked)} />
            Crypto F&amp;G Skew
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (paper quotes)
          </label>
          <div className="ml-auto flex gap-2">
            <button
              type="submit"
              disabled={acting}
              className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-500 px-3.5 py-2 text-xs font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-40"
            >
              {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {status?.running ? 'Restart MM' : 'Start MM'}
            </button>
            {status?.running && (
              <button
                type="button"
                onClick={() => void handleStop()}
                disabled={acting}
                className="inline-flex items-center gap-1.5 rounded-xl border border-rose-500/40 bg-rose-950/30 px-3.5 py-2 text-xs font-semibold text-rose-300 transition hover:bg-rose-950/60 disabled:opacity-40"
              >
                <Square className="h-3.5 w-3.5" />
                Stop
              </button>
            )}
          </div>
        </div>
      </form>
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 font-mono text-xs font-semibold text-white">{value}</div>
    </div>
  )
}
