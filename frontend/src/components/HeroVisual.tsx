import React, { useEffect, useRef, useState } from 'react'
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from 'motion/react'
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  Layers,
  Shield,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'

export function HeroVisual({
  onExplore,
}: {
  onExplore?: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isHovered, setIsHovered] = useState(false)
  const [activeTab, setActiveTab] = useState<'yes' | 'no'>('yes')
  const [matchCount, setMatchCount] = useState(248192)
  const [recentFills, setRecentFills] = useState<
    Array<{ id: number; price: number; size: number; side: 'YES' | 'NO'; time: string }>
  >([
    { id: 1, price: 68.5, size: 250, side: 'YES', time: '1s ago' },
    { id: 2, price: 68.0, size: 1200, side: 'YES', time: '3s ago' },
    { id: 3, price: 32.0, size: 400, side: 'NO', time: '5s ago' },
  ])

  // Mouse tilt physics using Motion springs
  const mouseX = useMotionValue(0)
  const mouseY = useMotionValue(0)

  const springConfig = { damping: 25, stiffness: 180 }
  const rotateX = useSpring(useTransform(mouseY, [-0.5, 0.5], [12, -12]), springConfig)
  const rotateY = useSpring(useTransform(mouseX, [-0.5, 0.5], [-12, 12]), springConfig)
  const glareX = useSpring(useTransform(mouseX, [-0.5, 0.5], [0, 100]), springConfig)
  const glareY = useSpring(useTransform(mouseY, [-0.5, 0.5], [0, 100]), springConfig)

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const x = (e.clientX - rect.left) / rect.width - 0.5
    const y = (e.clientY - rect.top) / rect.height - 0.5
    mouseX.set(x)
    mouseY.set(y)
  }

  const handleMouseLeave = () => {
    setIsHovered(false)
    mouseX.set(0)
    mouseY.set(0)
  }

  // Live orderbook tick simulation
  useEffect(() => {
    const timer = setInterval(() => {
      setMatchCount((prev) => prev + Math.floor(Math.random() * 4) + 1)
      if (Math.random() > 0.4) {
        const side = Math.random() > 0.35 ? 'YES' : 'NO'
        const price = side === 'YES' ? 68 + Math.floor(Math.random() * 5) * 0.1 : 32 - Math.floor(Math.random() * 5) * 0.1
        const size = Math.floor(Math.random() * 800) + 100
        setRecentFills((prev) => [
          { id: Date.now(), price: Number(price.toFixed(1)), size, side, time: 'just now' },
          ...prev.slice(0, 3),
        ])
      }
    }, 1800)
    return () => clearInterval(timer)
  }, [])

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      className="relative mx-auto w-full max-w-lg select-none [perspective:1200px]"
    >
      {/* Background ambient neon aura */}
      <motion.div
        animate={{
          scale: isHovered ? 1.08 : [1, 1.04, 1],
          opacity: isHovered ? 0.35 : 0.22,
        }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
        className="pointer-events-none absolute -inset-4 rounded-3xl bg-gradient-to-r from-emerald-500/30 via-teal-500/20 to-blue-500/30 blur-2xl"
      />

      {/* Main 3D Tilted Card */}
      <motion.div
        style={{
          rotateX,
          rotateY,
          transformStyle: 'preserve-3d',
        }}
        whileHover={{ scale: 1.02 }}
        transition={{ type: 'spring', damping: 20, stiffness: 200 }}
        className="relative overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-900/90 p-5 shadow-2xl backdrop-blur-xl transition-colors hover:border-emerald-500/50 sm:p-6"
      >
        {/* Dynamic Specular Glare */}
        <motion.div
          className="pointer-events-none absolute -inset-full opacity-0 transition-opacity duration-300"
          style={{
            opacity: isHovered ? 0.15 : 0,
            background: `radial-gradient(circle 320px at ${glareX.get()}% ${glareY.get()}%, rgba(255,255,255,0.8), transparent 60%)`,
          }}
        />

        {/* Top Status Bar: Engine State */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            <span className="font-mono text-[11px] font-semibold tracking-wider text-slate-300">
              CLOB SEQUENCER
            </span>
            <span className="rounded bg-emerald-950/80 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-emerald-400 border border-emerald-800/50">
              420μs
            </span>
          </div>

          <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
            <Cpu className="h-3 w-3 text-emerald-400" />
            <span>{matchCount.toLocaleString()} matches</span>
          </div>
        </div>

        {/* Live Market Preview Highlight */}
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300 border border-blue-500/20">
              Crypto / Macro
            </span>
            <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400">
              <TrendingUp className="h-3 w-3" />
              +14.2% today
            </span>
          </div>

          <h3 className="mt-2 text-base font-bold text-white sm:text-lg">
            Will Bitcoin trade above $100,000 before year-end?
          </h3>

          {/* Interactive Probability Meter */}
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3.5">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-emerald-400">YES</span>
                <span className="font-mono text-lg font-bold text-white">68¢</span>
                <span className="text-[10px] text-slate-400">($0.68)</span>
              </div>
              <div className="flex items-center gap-2 text-right">
                <span className="text-[10px] text-slate-400">($0.32)</span>
                <span className="font-mono text-lg font-bold text-white">32¢</span>
                <span className="font-semibold text-rose-400">NO</span>
              </div>
            </div>

            {/* Glowing Dual Probability Bar */}
            <div className="relative mt-2.5 h-3 w-full overflow-hidden rounded-full bg-slate-800">
              <motion.div
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-600 to-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.6)]"
                initial={{ width: '60%' }}
                animate={{ width: activeTab === 'yes' ? '68%' : '65%' }}
                transition={{ type: 'spring', damping: 20, stiffness: 120 }}
              />
              <motion.div
                className="absolute inset-y-0 right-0 bg-gradient-to-l from-rose-600 to-rose-400 shadow-[0_0_12px_rgba(244,63,94,0.6)]"
                initial={{ width: '40%' }}
                animate={{ width: activeTab === 'yes' ? '32%' : '35%' }}
                transition={{ type: 'spring', damping: 20, stiffness: 120 }}
              />
              {/* Mid-spread laser indicator */}
              <motion.div
                animate={{ left: activeTab === 'yes' ? '68%' : '65%' }}
                transition={{ type: 'spring', damping: 20, stiffness: 120 }}
                className="absolute top-0 bottom-0 w-1 -translate-x-1/2 bg-white shadow-[0_0_8px_#ffffff]"
              />
            </div>

            {/* Mini Interactive Toggle */}
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab('yes')}
                className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 font-semibold transition ${
                  activeTab === 'yes'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
                    : 'bg-slate-900/60 text-slate-400 border border-transparent hover:text-slate-200'
                }`}
              >
                <Zap className="h-3 w-3" />
                Inspect YES Orderbook
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('no')}
                className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 font-semibold transition ${
                  activeTab === 'no'
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-sm'
                    : 'bg-slate-900/60 text-slate-400 border border-transparent hover:text-slate-200'
                }`}
              >
                Inspect NO Depth
              </button>
            </div>
          </div>
        </div>

        {/* Live Order Matching Tape Animation */}
        <div className="mt-4">
          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400">
            <span className="flex items-center gap-1">
              <Activity className="h-3 w-3 text-emerald-400" />
              Live Engine Fills
            </span>
            <span className="font-mono text-[10px] text-slate-500">Sub-second execution</span>
          </div>

          <div className="mt-2 space-y-1.5">
            {recentFills.map((fill) => (
              <motion.div
                key={fill.id}
                initial={{ opacity: 0, y: -6, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="flex items-center justify-between rounded-lg border border-slate-800/60 bg-slate-950/40 px-2.5 py-1.5 text-xs font-mono"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block h-1.5 w-1.5 rounded-full ${
                      fill.side === 'YES' ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : 'bg-rose-400 shadow-[0_0_6px_#fb7185]'
                    }`}
                  />
                  <span className={fill.side === 'YES' ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                    {fill.side}
                  </span>
                  <span className="text-slate-200">{fill.price}¢</span>
                </div>
                <div className="flex items-center gap-3 text-slate-400 text-[11px]">
                  <span>{fill.size.toLocaleString()} shares</span>
                  <span className="text-slate-600 text-[10px]">{fill.time}</span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Interactive Badges at bottom */}
        <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-1 text-slate-400">
            <Shield className="h-3.5 w-3.5 text-emerald-400" />
            <span>USDC Collateral Vault</span>
          </div>
          {onExplore && (
            <button
              type="button"
              onClick={onExplore}
              className="flex items-center gap-1 font-semibold text-emerald-400 hover:text-emerald-300 transition"
            >
              Open Ticket <ArrowUpRight className="h-3 w-3" />
            </button>
          )}
        </div>
      </motion.div>

      {/* Floating Auxiliary Badges with Parallax */}
      <motion.div
        animate={{
          y: isHovered ? -8 : [0, -6, 0],
        }}
        transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          transformStyle: 'preserve-3d',
          translateZ: '30px',
        }}
        className="absolute -top-3 -right-3 hidden rounded-xl border border-emerald-500/30 bg-slate-900/90 px-3 py-1.5 text-xs font-medium text-emerald-300 shadow-xl backdrop-blur-md sm:flex sm:items-center sm:gap-1.5"
      >
        <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
        <span>Self-Custody Passkeys</span>
      </motion.div>

      <motion.div
        animate={{
          y: isHovered ? 6 : [0, 5, 0],
        }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut', delay: 0.8 }}
        style={{
          transformStyle: 'preserve-3d',
          translateZ: '25px',
        }}
        className="absolute -bottom-3 -left-3 hidden rounded-xl border border-slate-700 bg-slate-900/90 px-3 py-1.5 text-xs font-medium text-slate-300 shadow-xl backdrop-blur-md sm:flex sm:items-center sm:gap-1.5"
      >
        <Layers className="h-3.5 w-3.5 text-blue-400" />
        <span>Pro Desks & Copy Trading</span>
      </motion.div>
    </div>
  )
}
