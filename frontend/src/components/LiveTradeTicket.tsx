import React, { useEffect, useState } from 'react'
import { Loader2, ShieldAlert } from 'lucide-react'
import { api, type LiveMarket } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { useToast } from '../context/toast'

type Side = 'BUY' | 'SELL'
type OrderType = 'LIMIT' | 'MARKET'
const TIFS = ['GTC', 'IOC', 'FOK'] as const

export default function LiveTradeTicket({
  market,
  tokenId,
  onTokenChange,
  bids,
  asks,
  onPlaced,
}: {
  market: LiveMarket
  tokenId: string
  onTokenChange: (tokenId: string) => void
  bids: { price: number; size: number }[]
  asks: { price: number; size: number }[]
  onPlaced: () => void
}) {
  const { user } = useAuth()
  const { push } = useToast()
  const [side, setSide] = useState<Side>('BUY')
  const [orderType, setOrderType] = useState<OrderType>('LIMIT')
  const [price, setPrice] = useState<string>('')
  const [size, setSize] = useState<string>('')
  const [tif, setTif] = useState<(typeof TIFS)[number]>('GTC')
  const [postOnly, setPostOnly] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (orderType !== 'LIMIT' || price !== '') return
    const suggested = side === 'BUY' ? asks[0]?.price : bids[0]?.price
    if (suggested != null) setPrice(suggested.toFixed(2))
  }, [side, orderType, tokenId, asks, bids, price])

  const priceNum = parseFloat(price)
  const sizeNum = parseFloat(size)
  const effectivePrice =
    orderType === 'LIMIT'
      ? priceNum
      : side === 'BUY'
        ? (asks[0]?.price ?? market.best_ask ?? market.last_trade_price ?? 0.5)
        : (bids[0]?.price ?? market.best_bid ?? market.last_trade_price ?? 0.5)

  const warnings: string[] = []
  if (orderType === 'LIMIT' && price !== '') {
    if (Number.isNaN(priceNum) || priceNum < 0.01 || priceNum > 0.99) {
      warnings.push('Price must be between $0.01 and $0.99.')
    } else if (
      market.tick_size > 0 &&
      Math.abs(priceNum - Math.round(priceNum / market.tick_size) * market.tick_size) > 1e-9
    ) {
      warnings.push(`Price must align with tick size ($${market.tick_size}).`)
    }
  }
  if (size !== '' && (Number.isNaN(sizeNum) || sizeNum < market.min_order_size)) {
    warnings.push(`Minimum order size is ${market.min_order_size} shares.`)
  }

  const totalCost =
    !Number.isNaN(sizeNum) && sizeNum > 0 && !Number.isNaN(effectivePrice) && effectivePrice > 0
      ? sizeNum * effectivePrice
      : null

  const canSubmit =
    !submitting &&
    market.accepting_orders &&
    Boolean(user?.dexbuilder_wallet) &&
    warnings.length === 0 &&
    !Number.isNaN(sizeNum) &&
    sizeNum >= market.min_order_size &&
    (orderType === 'MARKET' || (!Number.isNaN(priceNum) && priceNum >= 0.01 && priceNum <= 0.99))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    try {
      const clientOrderId = `doly-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const res = await api.placeDexBuilderOrder({
        token_id: tokenId,
        side,
        price: effectivePrice.toFixed(4).replace(/\.?0+$/, ''),
        size: String(sizeNum),
        total_cost: totalCost != null ? totalCost.toFixed(4).replace(/\.?0+$/, '') : undefined,
        order_type: orderType,
        order_mode: orderType === 'MARKET' ? 'IOC' : tif,
        client_order_id: clientOrderId,
        post_only: orderType === 'LIMIT' ? postOnly : false,
      })
      push(
        `Order ${res.status || 'ACCEPTED'}: ${res.order_id} · ${side} ${sizeNum} @ $${effectivePrice.toFixed(2)}`,
        'info'
      )
      setSize('')
      onPlaced()
    } catch (err: any) {
      push(err?.message || 'Upstream rejected the order.', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Live Trade Ticket</h2>
        <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
          DexBuilder Broker
        </span>
      </div>

      {/* Outcome selector */}
      <div className="mb-3 grid grid-cols-2 gap-2">
        {market.tokens.map((t) => (
          <button
            key={t.token_id}
            type="button"
            onClick={() => {
              onTokenChange(t.token_id)
              setPrice('')
            }}
            className={`rounded-xl border px-3 py-2 text-left text-xs transition ${
              t.token_id === tokenId
                ? 'border-emerald-500/60 bg-emerald-500/10 text-white'
                : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200'
            }`}
          >
            <div className="font-medium">{t.symbol}</div>
            <div className="font-mono text-[11px] text-emerald-400">
              {t.price != null ? `${(t.price * 100).toFixed(1)}¢` : '—'}
            </div>
          </button>
        ))}
      </div>

      {/* Buy / Sell */}
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-slate-950 p-1">
        {(['BUY', 'SELL'] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setSide(s)
              setPrice('')
            }}
            className={`rounded-lg py-1.5 text-xs font-semibold transition ${
              side === s
                ? s === 'BUY'
                  ? 'bg-emerald-500 text-slate-950'
                  : 'bg-rose-500 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Order type */}
      <div className="mb-3 flex items-center gap-2 text-xs">
        {(['LIMIT', 'MARKET'] as const).map((ot) => (
          <button
            key={ot}
            type="button"
            onClick={() => setOrderType(ot)}
            className={`rounded-lg px-2.5 py-1 font-medium transition ${
              orderType === ot
                ? 'bg-slate-800 text-white'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {ot}
          </button>
        ))}
        {orderType === 'LIMIT' && (
          <div className="ml-auto flex gap-1">
            {TIFS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setTif(m)}
                className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${
                  tif === m ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        )}
      </div>

      {orderType === 'LIMIT' && (
        <label className="mb-3 block">
          <span className="text-[11px] text-slate-400">Limit price ($)</span>
          <input
            type="number"
            step={market.tick_size || 0.01}
            min={0.01}
            max={0.99}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="0.50"
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-sm text-white outline-none focus:border-emerald-500/60"
          />
        </label>
      )}

      <label className="mb-3 block">
        <span className="text-[11px] text-slate-400">Shares (min {market.min_order_size})</span>
        <input
          type="number"
          step="any"
          min={market.min_order_size}
          value={size}
          onChange={(e) => setSize(e.target.value)}
          placeholder={String(market.min_order_size)}
          className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-sm text-white outline-none focus:border-emerald-500/60"
        />
      </label>

      {orderType === 'LIMIT' && (
        <label className="mb-3 flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={postOnly}
            onChange={(e) => setPostOnly(e.target.checked)}
            className="rounded border-slate-700 bg-slate-950"
          />
          Post-only (Maker)
        </label>
      )}

      {totalCost != null && (
        <div className="mb-3 flex items-center justify-between rounded-xl bg-slate-950/70 px-3 py-2 text-xs">
          <span className="text-slate-400">Est. notional</span>
          <span className="font-mono font-semibold text-white">${totalCost.toFixed(2)}</span>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mb-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
          {warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      )}

      {!user ? (
        <div className="mb-3 flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/70 p-2.5 text-[11px] text-slate-400">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          Sign in and link a wallet to place live orders.
        </div>
      ) : !user.dexbuilder_wallet ? (
        <div className="mb-3 flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
          Connect or set your DexBuilder wallet before trading.
        </div>
      ) : null}

      <button
        type="submit"
        disabled={!canSubmit}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-2.5 text-xs font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {!market.accepting_orders ? 'Market closed' : `Place ${side} order`}
      </button>
    </form>
  )
}
