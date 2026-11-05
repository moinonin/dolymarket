import React, { useEffect, useRef, useState } from 'react'
import { api, type Market, type OutcomeToken } from '../api/client'
import {
  addPendingOrder,
  confirmPendingOrder,
  rejectPendingOrder,
} from '../api/optimisticOrders'
import { FeePreview } from './ui'
import { useToast } from '../context/toast'
import { useAuth } from '../auth/AuthProvider'

type Side = 'BUY' | 'SELL'
type OrderType = 'LIMIT' | 'MARKET'

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
  const submitRef = useRef<() => void>(() => {})

  // Auto-fill limit price with the visible opposite side.
  useEffect(() => {
    if (orderType !== 'LIMIT') return
    if (price !== '') return
    const suggestion = side === 'BUY' ? asks[0]?.price : bids[0]?.price
    if (suggestion != null) setPrice(suggestion.toFixed(2))
  }, [side, orderType, token.token_id])

  const priceNum = parseFloat(price)
  const amountNum = parseFloat(amount)

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

  function submit() {
    if (!user) {
      push('Sign in first to place orders.', 'error')
      return
    }
    if (submitting || warnings.length > 0) return
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

      <div className="grid grid-cols-2 gap-1.5">
        <button
          onClick={() => setSide('BUY')}
          className={`rounded-lg py-2 text-sm font-bold transition ${
            side === 'BUY'
              ? 'bg-emerald-500 text-slate-950'
              : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
          }`}
        >
          Buy
        </button>
        <button
          onClick={() => setSide('SELL')}
          className={`rounded-lg py-2 text-sm font-bold transition ${
            side === 'SELL'
              ? 'bg-rose-500 text-slate-950'
              : 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
          }`}
        >
          Sell
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-1.5 text-xs">
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

        <FeePreview shares={amountNum || 0} price={priceNum || 0} feeRate={feeRate} />
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
        disabled={submitting || warnings.length > 0 || !user}
        className={`mt-4 w-full rounded-lg py-2.5 text-sm font-bold text-slate-950 transition disabled:cursor-not-allowed disabled:opacity-40 ${
          side === 'BUY' ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-rose-500 hover:bg-rose-400'
        }`}
      >
        {submitting ? 'Submitting…' : `${side === 'BUY' ? 'Buy' : 'Sell'} ${token.symbol}`}
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
