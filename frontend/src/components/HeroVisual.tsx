import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from 'motion/react'
import {
  Activity,
  ArrowUpRight,
  Radio,
  ShieldAlert,
  TrendingUp,
} from 'lucide-react'

type Profile = 'balanced' | 'momentum' | 'vol_conservative' | 'microstructure'

const PROFILES: { key: Profile; label: string }[] = [
  { key: 'balanced', label: 'Balanced' },
  { key: 'momentum', label: 'Momentum' },
  { key: 'vol_conservative', label: 'Vol' },
  { key: 'microstructure', label: 'Book' },
]

interface FearGreedReading {
  timestamp: number
  score_0_100: number
  sentiment_label: string
  structural_stability: number
  regime_state: string
  ewi: number
  v_alpha: number
  m_alpha: number
  btc_price: number
  funding_8h_bps: number
  return_14d_pct: number
  dvol: number
  bid_ask_imbalance: number
  early_warning: boolean
  profile: string
  source: string
}

function gradColor(score: number): string {
  const t = Math.max(0, Math.min(1, score / 100))
  const c1 = t < 0.5 ? [239, 68, 68] : [249, 115, 22]
  const c2 = t < 0.5 ? [249, 115, 22] : [34, 197, 94]
  const f = t < 0.5 ? t * 2 : (t - 0.5) * 2
  const r = Math.round(c1[0] + (c2[0] - c1[0]) * f)
  const g = Math.round(c1[1] + (c2[1] - c1[1]) * f)
  const b = Math.round(c1[2] + (c2[2] - c1[2]) * f)
  return `rgb(${r},${g},${b})`
}

export function HeroVisual({
  onExplore,
}: {
  onExplore?: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isHovered, setIsHovered] = useState(false)
  const [profile, setProfile] = useState<Profile>('microstructure')
  const [data, setData] = useState<FearGreedReading | null>(null)
  const [wsConnected, setWsConnected] = useState(false)

  // 3D tilt physics
  const mouseX = useMotionValue(0)
  const mouseY = useMotionValue(0)
  const springConfig = { damping: 25, stiffness: 180 }
  const rotateX = useSpring(useTransform(mouseY, [-0.5, 0.5], [10, -10]), springConfig)
  const rotateY = useSpring(useTransform(mouseX, [-0.5, 0.5], [-10, 10]), springConfig)
  const glareX = useSpring(useTransform(mouseX, [-0.5, 0.5], [0, 100]), springConfig)
  const glareY = useSpring(useTransform(mouseY, [-0.5, 0.5], [0, 100]), springConfig)

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    mouseX.set((e.clientX - rect.left) / rect.width - 0.5)
    mouseY.set((e.clientY - rect.top) / rect.height - 0.5)
  }

  const handleMouseLeave = () => {
    setIsHovered(false)
    mouseX.set(0)
    mouseY.set(0)
  }

  const fetchLatest = useCallback(async (p: Profile) => {
    try {
      const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')
      const res = await fetch(`${apiBase}/api/v1/feargreed/latest?profile=${encodeURIComponent(p)}`)
      if (res.ok) {
        const json = (await res.json()) as FearGreedReading
        setData(json)
      }
    } catch {
      /* keep last reading */
    }
  }, [])

  useEffect(() => {
    void fetchLatest(profile)
    const poll = window.setInterval(() => void fetchLatest(profile), 5000)

    const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')
    const wsProto = apiBase
      ? apiBase.startsWith('https')
        ? 'wss'
        : 'ws'
      : window.location.protocol === 'https:'
        ? 'wss'
        : 'ws'
    const wsHost = apiBase ? apiBase.replace(/^https?:\/\//, '') : window.location.host
    const wsUrl = `${wsProto}://${wsHost}/ws/feargreed?profile=${encodeURIComponent(profile)}`

    let ws: WebSocket | null = null
    let closed = false
    try {
      ws = new WebSocket(wsUrl)
      ws.onopen = () => {
        if (closed) {
          ws?.close()
          return
        }
        setWsConnected(true)
      }
      ws.onmessage = (ev) => {
        try {
          const reading = JSON.parse(ev.data) as FearGreedReading
          if (!closed) setData(reading)
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        if (!closed) setWsConnected(false)
      }
      ws.onerror = () => {
        if (!closed) setWsConnected(false)
      }
    } catch {
      setWsConnected(false)
    }

    return () => {
      closed = true
      window.clearInterval(poll)
      if (ws) {
        ws.onmessage = null
        ws.onclose = null
        if (ws.readyState === WebSocket.OPEN) {
          ws.close()
        }
      }
    }
  }, [profile, fetchLatest])

  const score = data?.score_0_100 ?? null
  const label = data ? data.sentiment_label.replace(/_/g, ' ') : 'CONNECTING…'
  const ang = score !== null ? Math.PI - (score / 100) * Math.PI : Math.PI / 2
  const nx = 130 + 86 * Math.cos(ang)
  const ny = 130 - 86 * Math.sin(ang)

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      className="relative flex w-full items-center justify-center py-4 lg:py-0"
      style={{ perspective: 1200 }}
    >
      <div className="pointer-events-none absolute -inset-4 rounded-3xl bg-gradient-to-tr from-emerald-500/15 via-blue-500/10 to-transparent blur-3xl opacity-60" />

      <motion.div
        style={{
          rotateX,
          rotateY,
          transformStyle: 'preserve-3d',
        }}
        className="relative w-full max-w-[460px] rounded-2xl border border-slate-700/80 bg-slate-900/90 p-5 shadow-2xl shadow-emerald-950/30 backdrop-blur-xl"
      >
        <motion.div
          className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300"
          style={{
            opacity: isHovered ? 0.22 : 0,
            background: useTransform(
              [glareX, glareY],
              ([x, y]) =>
                `radial-gradient(circle at ${x}% ${y}%, rgba(255,255,255,0.22) 0%, transparent 60%)`
            ),
          }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
            </span>
            <span className="text-[11px] font-semibold tracking-wider text-slate-200 uppercase">
              GRG BTC Fear &amp; Greed
            </span>
          </div>
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-950/80 px-2 py-0.5 text-[10px] font-mono text-slate-400">
            <Radio className={`h-3 w-3 ${wsConnected ? 'text-emerald-400' : 'text-amber-400'}`} />
            {wsConnected ? 'Gate.io WS' : 'Gate.io REST'}
          </span>
        </div>

        {/* Profile switcher */}
        <div className="mt-3 flex items-center justify-between gap-1 rounded-xl bg-slate-950/80 p-1">
          {PROFILES.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setProfile(p.key)}
              className={`flex-1 rounded-lg py-1 text-[10px] font-medium transition ${
                profile === p.key
                  ? 'bg-slate-800 text-emerald-300 shadow-sm'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* SVG Gauge */}
        <div className="mt-2 px-4">
          <svg viewBox="0 0 260 150" className="w-full h-auto overflow-visible">
            <defs>
              <linearGradient id="heroFgGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#ef4444" />
                <stop offset="50%" stopColor="#f97316" />
                <stop offset="100%" stopColor="#22c55e" />
              </linearGradient>
            </defs>
            <path
              d="M 25 130 A 105 105 0 0 1 235 130"
              fill="none"
              stroke="rgba(30,41,59,0.9)"
              strokeWidth="22"
              strokeLinecap="round"
            />
            <path
              d="M 25 130 A 105 105 0 0 1 235 130"
              fill="none"
              stroke="url(#heroFgGrad)"
              strokeWidth="18"
              strokeLinecap="round"
            />
            <line
              x1="130"
              y1="130"
              x2={nx.toFixed(1)}
              y2={ny.toFixed(1)}
              stroke="#f8fafc"
              strokeWidth="3.5"
              strokeLinecap="round"
            />
            <circle cx="130" cy="130" r="6" fill="#f8fafc" />
          </svg>
        </div>

        {/* Score & Regime */}
        <div className="-mt-2 text-center">
          <div
            className="font-mono text-4xl font-bold tabular-nums"
            style={{ color: score !== null ? gradColor(score) : '#94a3b8' }}
          >
            {score !== null ? score.toFixed(1) : '--'}
          </div>
          <div className="mt-0.5 text-xs font-semibold tracking-wider text-white">
            {label}
          </div>
          <div className="mt-2 flex justify-center">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-0.5 font-mono text-[11px] ${
                data?.early_warning
                  ? 'border-amber-500/60 bg-amber-950/60 text-amber-300'
                  : 'border-slate-700 bg-slate-800/80 text-slate-300'
              }`}
            >
              {data?.early_warning ? (
                <ShieldAlert className="h-3 w-3 text-amber-400" />
              ) : (
                <Activity className="h-3 w-3 text-emerald-400" />
              )}
              {data ? `${data.regime_state} · EWI ${data.ewi.toFixed(3)}` : 'CALIBRATING'}
            </span>
          </div>
        </div>

        {/* Live Gate.io telemetry strip */}
        <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl border border-slate-800/90 bg-slate-950/70 p-2.5 text-center font-mono">
          <div>
            <div className="text-[9px] uppercase text-slate-500">BTC/USDT</div>
            <div className="text-xs font-semibold text-white">
              {data?.btc_price ? `$${data.btc_price.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}
            </div>
          </div>
          <div>
            <div className="text-[9px] uppercase text-slate-500">1h Ret (10s)</div>
            <div className={`text-xs font-semibold ${(data?.return_14d_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {data ? `${data.return_14d_pct >= 0 ? '+' : ''}${data.return_14d_pct.toFixed(1)}%` : '—'}
            </div>
          </div>
          <div>
            <div className="text-[9px] uppercase text-slate-500">Book Imb</div>
            <div className={`text-xs font-semibold ${(data?.bid_ask_imbalance ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {data ? `${data.bid_ask_imbalance >= 0 ? '+' : ''}${(data.bid_ask_imbalance * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        </div>

        <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
          <span>0 Fear</span>
          <span>50 Neutral</span>
          <span>100 Greed</span>
        </div>

        {onExplore && (
          <button
            type="button"
            onClick={onExplore}
            className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 py-2 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20"
          >
            <TrendingUp className="h-3.5 w-3.5" />
            Trade BTC Sentiment Markets
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        )}
      </motion.div>
    </div>
  )
}
