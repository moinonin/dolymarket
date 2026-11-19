import React, { useEffect, useRef, useState } from 'react'
import { api, type AgxBalance, type Market, type OutcomeToken } from '../api/client'
import {
  addPendingOrder,
  confirmPendingOrder,
  rejectPendingOrder,
} from '../api/optimisticOrders'
import { FeePreview } from './ui'
import { useToast } from '../context/toast'
import { useAuth } from '../auth/AuthProvider'

type Side = 'BUY' | 'SELL'
type OrderType = 'LIMIT' | 'MARKET' | 'SMART'

const TIFS = ['GTC', 'IOC', 'FOK'] as const

export default function TradeTicket({
  market,
  token,
  onTokenChange,
  lastPrice,
  bids,
  asks,
  feeRate,
  onPlaced,
}: {
  market: Market
  token: OutcomeToken
  onTokenChange: (t: OutcomeToken) => void
  lastPrice: number | null
  bids: { price: number; size: number }[]
  asks: { price: number; size: number }[]
  feeRate: number
  onPlaced: () => void
}) {
  const { user } = useAuth()
  const { push } = useToast()
  const [side, setSide] = useState<Side>('BUY')
  const [orderType, setOrderType] = useState<OrderType>('LIMIT')
  const [price, setPrice] = useState<string>('')
  const [amount, setAmount] = useState<string>('')
  const [tif, setTif] = useState<(typeof TIFS)[number]>('GTC')
  const [postOnly, setPostOnly] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [agx, setAgx] = useState<AgxBalance | null>(null)
  const [smartPreview, setSmartPreview] = useState<Awaited<ReturnType<typeof api.smartQuote>> | null>(null)
  const [health, setHealth] = useState<{ ewi: number; regime_state: string; score_0_100: number } | null>(null)
  const submitRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false
    const pull = () => {
      api
        .getFearGreedLatest('microstructure')
        .then((r) => {
          if (!cancelled) setHealth(r)
        })
        .catch(() => {})
    }
    pull()
    const iv = window.setInterval(pull, 15000)
    return () => {
      cancelled = true
      window.clearInterval(iv)
    }
  }, [])

  // The AGX tier is advisory UI only: it previews the taker discount the
  // backend applies. A missing balance row or failed read simply shows nothing.
  useEffect(() => {
    if (!user) {
      setAgx(null)
      return
    }
    let cancelled = false
    api
      .getAgxBalance()
      .then((row) => {
        if (!cancelled) setAgx(row)
      })
      .catch(() => {
        if (!cancelled) setAgx(null)
      })
    return () => {
      cancelled = true
    }
  }, [user?.id])

  const agxDiscount = Number(agx?.discount_rate ?? 0)

  // Auto-fill limit price with the visible opposite side.
  useEffect(() => {
    if (orderType !== 'LIMIT') return
    if (price !== '') return
    const suggestion = side === 'BUY' ? asks[0]?.price : bids[0]?.price
    if (suggestion != null) setPrice(suggestion.toFixed(2))
  }, [side, orderType, token.token_id])

  const priceNum = parseFloat(price)
  const amountNum = parseFloat(amount)
  const bestBid = bids[0]?.price
  const bestAsk = asks[0]?.price
  const spreadCents =
    bestBid != null && bestAsk != null && bestAsk >= bestBid
      ? (bestAsk - bestBid) * 100
      : null
  const highToxicity =
    (health != null && health.ewi >= 0.45) ||
    (spreadCents != null && spreadCents >= 6) ||
    bestBid == null ||
    bestAsk == null

  useEffect(() => {
    if (orderType !== 'SMART' || Number.isNaN(amountNum) || amountNum <= 0) {
      setSmartPreview(null)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      api
        .smartQuote({
          market_id: market.id,
          token_id: token.token_id,
          side,
          shares: amountNum,
        })
        .then((q) => {
          if (!cancelled) setSmartPreview(q)
        })
        .catch(() => {
          if (!cancelled) setSmartPreview(null)
        })
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [orderType, market.id, token.token_id, side, amountNum])

  // Pre-order validation warnings (mirror backend business rules).
  const warnings: string[] = []
  if (orderType === 'LIMIT') {
    if (Number.isNaN(priceNum) || priceNum <= 0) {
      if (price !== '') warnings.push('Enter a price in dollars (e.g. 0.55).')
    } else {
      if (priceNum < 0.01 || priceNum > 0.99)
        warnings.push('Price must be between $0.01 and $0.99.')
      if (Math.abs(priceNum - Math.round(priceNum / market.tick_size) * market.tick_size) > 1e-9)
        warnings.push(`Price must be a multiple of the tick size (¢${(market.tick_size * 100).toFixed(0)}).`)
    }
  }
  if (!Number.isNaN(amountNum)) {
    if (amountNum < market.min_order_size)
      warnings.push(`Minimum order size is ${market.min_order_size} shares.`)
  }

  const cost =
    !Number.isNaN(amountNum) && (orderType === 'MARKET' || !Number.isNaN(priceNum))
      ? amountNum * (orderType === 'MARKET' ? lastPrice ?? 0 : priceNum)
      : null
  const maxProfit = side === 'BUY' && cost ? amountNum - cost : side === 'SELL' ? null : null
  const returnPct =
    cost != null && side === 'BUY' && amountNum > 0
      ? ((amountNum - cost) / cost) * 100
      : null

  const isMarketActive = market.status === 'ACTIVE'

  function submit() {
    if (!isMarketActive) return
    if (!user) {
      push('Sign in first to place orders.', 'error')
      return
    }
    if (submitting || warnings.length > 0) return
    if (orderType === 'SMART') {
      if (Number.isNaN(amountNum) || amountNum <= 0) return
      setSubmitting(true)
      api
        .placeSmartOrder({
          market_id: market.id,
          token_id: token.token_id,
          side,
          shares: amountNum,
        })
        .then((res) => {
          push(
            `Smart Route ${res.status}: ${res.total_filled_shares} sh @ $${res.blended_avg_price.toFixed(3)} (CLOB ${res.clob_filled_shares} / AMM ${res.amm_filled_shares})`,
            'info'
          )
          setAmount('')
          setSmartPreview(null)
          onPlaced()
        })
        .catch((err) => {
          push(err.message || 'Smart order failed', 'error')
        })
        .finally(() => setSubmitting(false))
      return
    }
    const optimistic =
      orderType === 'LIMIT'
        ? addPendingOrder({
            id: null,
            market_id: market.id,
            token_id: token.token_id,
            side,
            type: orderType,
            price: priceNum,
            amount: amountNum,
            filled_amount: 0,
            status: 'PENDING',
            time_in_force: tif,
            created_at: new Date().toISOString(),
          })
        : null
    setSubmitting(true)
    api
      .submitOrder({
        market_id: market.id,
        token_id: token.token_id,
        side,
        type: orderType,
        price: orderType === 'LIMIT' && price !== '' ? priceNum : null,
        amount: amountNum,
        time_in_force: tif,
        post_only: postOnly,
      })
      .then((res) => {
        if (optimistic) confirmPendingOrder(optimistic, res.order)
        const fills = res.fills?.length || 0
        push(
          fills > 0
            ? `${res.order.status}: matched ${fills} fill${fills > 1 ? 's' : ''} on ${token.symbol} @ $${res.fills[0].price.toFixed(2)}`
            : res.order.status === 'FILLED' || res.order.status === 'OPEN'
              ? `Order ${res.order.status.toLowerCase()} — resting on the book.`
              : `Order ${res.order.status.replace('_', ' ').toLowerCase()}.`,
          'info'
        )
        setAmount('')
        onPlaced()
      })
      .catch((err) => {
        // Optimistic row is rolled back; the API client raises the toast.
        if (optimistic) rejectPendingOrder(optimistic)
        push(err.message || 'Order rejected', 'error')
      })
      .finally(() => setSubmitting(false))
  }

  submitRef.current = submit

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      const typing =
        tag === 'input' || tag === 'textarea' || tag === 'select' ||
        target?.isContentEditable === true

      if (event.key === 'Escape') {
        setPrice('')
        setAmount('')
        target?.blur?.()
        return
      }
      if (event.key === 'Enter') {
        if (tag === 'textarea' || tag === 'button' || tag === 'a') return
        event.preventDefault()
        submitRef.current()
        return
      }
      if (typing) return
      const key = event.key.toLowerCase()
      if (key === 'b') setSide('BUY')
      if (key === 's') setSide('SELL')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex gap-1">
        {market.tokens.map((t) => (
          <button
            key={t.token_id}
            onClick={() => onTokenChange(t)}
            className={`flex-1 rounded-lg px-2 py-1.5 text-xs font-semibold transition ${
              t.token_id === token.token_id
                ? 'bg-slate-800 text-white ring-1 ring-slate-600'
                : 'text-slate-500 hover:bg-slate-800/60'
            }`}
          >
            {t.symbol}
          </button>
        ))}
      </div>

      <div className="mb-3 flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-1.5 text-[11px]">
        <span className="text-slate-400">
          Health:{' '}
          <span
            className={`font-semibold ${
              health?.ewi != null && health.ewi >= 0.75
                ? 'text-rose-400'
                : health?.ewi != null && health.ewi >= 0.45
                  ? 'text-amber-300'
                  : 'text-emerald-400'
            }`}
          >
            {health?.regime_state ?? 'STABLE'}
          </span>
          {health != null && <span className="ml-1 font-mono text-slate-500">(EWI {health.ewi.toFixed(2)})</span>}
        </span>
        <span className="font-mono text-slate-300">
          {spreadCents != null ? `Spread ${spreadCents.toFixed(1)}¢` : 'Thin book'}
        </span>
      </div>
      {highToxicity && orderType === 'MARKET' && (
        <div className="mb-3 rounded-lg border border-amber-500/35 bg-amber-950/30 px-2.5 py-1.5 text-[11px] text-amber-200">
          ⚠ Elevated spread/toxicity — use <span className="font-semibold">Limit</span> or{' '}
          <span className="font-semibold">Smart Route</span> to cap slippage.
        </div>
      )}

      {!isMarketActive && (
        <div className="mb-3 rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
          Market is <span className="font-semibold text-white">{market.status.replace(/_/g, ' ').toLowerCase()}</span> — trading is disabled.
        </div>
      )}

      <div className="grid grid-cols-2 gap-1.5">
        <button
          onClick={() => setSide('BUY')}
          disabled={!isMarketActive}
          className={`rounded-lg py-2 text-sm font-bold transition disabled:cursor-not-allowed disabled:opacity-40 ${
            side === 'BUY'
              ? 'bg-emerald-500 text-slate-950'
              : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
          }`}
        >
          Buy
        </button>
        <button
          onClick={() => setSide('SELL')}
          disabled={!isMarketActive}
          className={`rounded-lg py-2 text-sm font-bold transition disabled:cursor-not-allowed disabled:opacity-40 ${
            side === 'SELL'
              ? 'bg-rose-500 text-slate-950'
              : 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
          }`}
        >
          Sell
        </button>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-1.5 text-xs">
        <button
          onClick={() => setOrderType('MARKET')}
          className={`rounded-lg py-1.5 font-medium transition ${
            orderType === 'MARKET' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-800/50'
          }`}
        >
          Market
        </button>
        <button
          onClick={() => setOrderType('LIMIT')}
          className={`rounded-lg py-1.5 font-medium transition ${
            orderType === 'LIMIT' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-800/50'
          }`}
        >
          Limit
        </button>
        <button
          onClick={() => setOrderType('SMART')}
          className={`rounded-lg py-1.5 font-medium transition ${
            orderType === 'SMART'
              ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40'
              : 'text-slate-400 hover:bg-slate-800/50'
          }`}
        >
          Smart Route
        </button>
      </div>

      <div className="mt-3 space-y-2.5">
        {orderType === 'LIMIT' ? (
          <label className="block">
            <span className="text-[11px] font-medium text-slate-400">Limit price (¢{(market.tick_size * 100).toFixed(0)} tick)</span>
            <input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="0.50"
              inputMode="decimal"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm outline-none transition focus:border-blue-500"
            />
          </label>
        ) : orderType === 'SMART' ? (
          <div className="rounded-lg border border-emerald-500/25 bg-emerald-950/20 px-3 py-2 text-xs text-slate-300">
            <div className="flex items-center justify-between">
              <span className="font-medium text-emerald-300">Atomic CLOB + AMM Router</span>
              {smartPreview?.clob_exhausted && smartPreview.amm_shares > 0 && (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                  AMM Backstop Active
                </span>
              )}
            </div>
            {smartPreview ? (
              <div className="mt-1.5 space-y-0.5 font-mono text-[11px] text-slate-400">
                <div className="flex justify-between">
                  <span>CLOB leg</span>
                  <span className="text-slate-200">
                    {smartPreview.clob_shares} sh @ ${smartPreview.clob_avg_price.toFixed(3)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>AMM leg</span>
                  <span className="text-slate-200">
                    {smartPreview.amm_shares} sh @ ${smartPreview.amm_avg_price.toFixed(3)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-slate-800/80 pt-1 text-emerald-300">
                  <span>Blended avg</span>
                  <span>${smartPreview.blended_avg_price.toFixed(3)}</span>
                </div>
              </div>
            ) : (
              <p className="mt-1 text-[11px] text-slate-500">
                Enter share size to preview CLOB + AMM split.
              </p>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-400">
            Executes at best resting price{' '}
            <span className="font-mono text-slate-200">
              {(side === 'BUY' ? asks[0]?.price : bids[0]?.price) != null
                ? `$${((side === 'BUY' ? asks[0] : bids[0])!.price).toFixed(2)}`
                : '— no liquidity'}
            </span>
          </div>
        )}

        <label className="block">
          <span className="text-[11px] font-medium text-slate-400">Shares (min {market.min_order_size})</span>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="25"
            inputMode="decimal"
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm outline-none transition focus:border-blue-500"
          />
        </label>

        {cost != null && (
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400">Max profit</span>
              <span className="font-mono text-emerald-400">
                {maxProfit != null ? `$${maxProfit.toFixed(2)}` : '—'}
              </span>
            </div>
            <div className="mt-0.5 flex justify-between">
              <span className="text-slate-400">Potential return</span>
              <span className="font-mono text-slate-200">
                {returnPct != null && Number.isFinite(returnPct) ? `${returnPct.toFixed(1)}%` : '—'}
              </span>
            </div>
          </div>
        )}

        <div>
          <span className="text-[11px] font-medium text-slate-400">Time in force</span>
          <div className="mt-1 grid grid-cols-3 gap-1">
            {TIFS.map((t) => (
              <button
                key={t}
                onClick={() => setTif(t)}
                className={`rounded-md py-1 text-[11px] font-semibold transition ${
                  tif === t ? 'bg-slate-800 text-white ring-1 ring-slate-600' : 'text-slate-500 hover:bg-slate-800/50'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <p className="mt-1 text-[10px] text-slate-500">
            {tif === 'GTC'
              ? 'Good-Til-Cancelled: rests on book until filled or cancelled.'
              : tif === 'IOC'
                ? 'Immediate-Or-Cancel: fills available size now, cancels remainder.'
                : 'Fill-Or-Kill: fills 100% immediately or cancels whole order.'}
          </p>
        </div>

        {orderType === 'LIMIT' && (
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={postOnly}
              onChange={(e) => setPostOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-emerald-500"
            />
            Post-only <span className="text-slate-600">(maker guarantee)</span>
          </label>
        )}

        {agx && agxDiscount > 0 && (
          <div className="flex items-center justify-between rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-300">
            <span>
              AGX {agx.tier_name} · Tier {agx.tier}
            </span>
            <span className="font-mono">
              {(agxDiscount * 100).toFixed(1)}% off taker fees
            </span>
          </div>
        )}

        <FeePreview
          shares={amountNum || 0}
          price={priceNum || 0}
          feeRate={feeRate}
          discountRate={agxDiscount}
        />
      </div>

      {warnings.length > 0 && (
        <div className="mt-3 space-y-1 rounded-lg border border-amber-800/50 bg-amber-950/40 px-3 py-2">
          {warnings.map((w, i) => (
            <p key={i} className="text-[11px] leading-snug text-amber-300">
              ⚠ {w}
            </p>
          ))}
        </div>
      )}

      <button
        onClick={submit}
        disabled={!isMarketActive || submitting || warnings.length > 0 || !user}
        className={`mt-4 w-full rounded-lg py-2.5 text-sm font-bold text-slate-950 transition disabled:cursor-not-allowed disabled:opacity-40 ${
          side === 'BUY' ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-rose-500 hover:bg-rose-400'
        }`}
      >
        {!isMarketActive
          ? market.status === 'RESOLVED'
            ? 'Market Resolved'
            : 'Trading Closed'
          : submitting
            ? 'Submitting…'
            : `${side === 'BUY' ? 'Buy' : 'Sell'} ${token.symbol}`}
      </button>
      {!user && <p className="mt-2 text-center text-[11px] text-slate-500">Sign in to place orders</p>}
      <p className="mt-2 text-center text-[10px] text-slate-600">
        Hotkeys: <span className="text-slate-400">B</span> buy ·{' '}
        <span className="text-slate-400">S</span> sell ·{' '}
        <span className="text-slate-400">Enter</span> submit ·{' '}
        <span className="text-slate-400">Esc</span> clear
      </p>
    </div>
  )
}
