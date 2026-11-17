import React from 'react'
import {
  Activity,
  BookOpen,
  Cpu,
  ExternalLink,
  Gavel,
  ShieldCheck,
  Terminal,
  TrendingUp,
} from 'lucide-react'

export function Footer({
  onNavigate,
}: {
  onNavigate: (to: string) => void
}) {
  const docsBase = import.meta.env.VITE_DOCS_URL || '/docs/'

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <footer className="border-t border-slate-800/80 bg-slate-950/70 pt-14 pb-10 text-xs font-geist-mono">
      <div className="mx-auto max-w-[1840px] px-4 sm:px-6 lg:px-8 2xl:px-12">
        <div className="grid grid-cols-1 gap-10 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
          {/* Brand & System Status */}
          <div className="sm:col-span-2 md:col-span-3 lg:col-span-2">
            <button
              type="button"
              onClick={scrollToTop}
              title="Scroll to top"
              className="group flex items-center gap-2 text-left text-base font-bold text-white transition hover:text-emerald-400"
            >
              <img
                src="/logo.png"
                alt=""
                width={24}
                height={24}
                className="h-6 w-6 shrink-0 object-contain transition group-hover:scale-105"
              />
              <span>AlgoXen</span>
            </button>
            <p className="mt-3 max-w-sm text-xs leading-relaxed text-slate-400">
              Prediction market protocol powered by a deterministic central limit order book (CLOB). Low-latency matching, verifiable oracle resolution, and simulated USDC settlement.
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 px-3 py-1.5 text-[11px] text-emerald-300">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
                <span>ENGINE: OPERATIONAL (420μs)</span>
              </div>

              <div className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-1.5 text-[11px] text-slate-400">
                <Cpu className="h-3.5 w-3.5 text-blue-400" />
                <span>CLOB SEQUENCER v4</span>
              </div>
            </div>
          </div>

          {/* Markets & Trading */}
          <div>
            <h4 className="font-semibold uppercase tracking-wider text-slate-200">
              Markets & Trading
            </h4>
            <ul className="mt-3 space-y-2 text-slate-400">
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('live')}
                  className="flex items-center gap-1.5 transition hover:text-emerald-400"
                >
                  <Activity className="h-3 w-3 text-emerald-400" />
                  Live Markets
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('desks')}
                  className="flex items-center gap-1.5 transition hover:text-emerald-400"
                >
                  <TrendingUp className="h-3 w-3 text-blue-400" />
                  Pro Desks & Copy
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('trades')}
                  className="transition hover:text-slate-200"
                >
                  Trade Tape
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('settled')}
                  className="transition hover:text-slate-200"
                >
                  Settled Contracts
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('tags')}
                  className="transition hover:text-slate-200"
                >
                  Category Taxonomy
                </button>
              </li>
            </ul>
          </div>

          {/* Protocol & Vault */}
          <div>
            <h4 className="font-semibold uppercase tracking-wider text-slate-200">
              Protocol & Vault
            </h4>
            <ul className="mt-3 space-y-2 text-slate-400">
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('portfolio')}
                  className="transition hover:text-emerald-400"
                >
                  Collateral & Positions
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('agx')}
                  className="transition hover:text-emerald-400"
                >
                  AGX Governance Staking
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('resolution')}
                  className="flex items-center gap-1.5 transition hover:text-slate-200"
                >
                  <Gavel className="h-3 w-3 text-amber-400" />
                  Dispute & Resolution
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate('activity')}
                  className="transition hover:text-slate-200"
                >
                  Copy Execution Feed
                </button>
              </li>
            </ul>
          </div>

          {/* Documentation & Developers */}
          <div>
            <h4 className="font-semibold uppercase tracking-wider text-slate-200">
              Documentation
            </h4>
            <ul className="mt-3 space-y-2 text-slate-400">
              <li>
                <a
                  href={`${docsBase}getting-started/quickstart/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-emerald-400"
                >
                  Quickstart Guide <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </li>
              <li>
                <a
                  href={`${docsBase}api-reference/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-emerald-400"
                >
                  <Terminal className="h-3 w-3 text-emerald-400" />
                  API Reference <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </li>
              <li>
                <a
                  href={`${docsBase}trading/fees/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-slate-200"
                >
                  Trading Fee Schedule <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </li>
              <li>
                <a
                  href={`${docsBase}security-audit/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-slate-200"
                >
                  <ShieldCheck className="h-3 w-3 text-accent" />
                  Security Audit <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </li>
              <li>
                <a
                  href={`${docsBase}faq/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-slate-200"
                >
                  System Architecture & FAQ <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Disclaimers & Legal Bar */}
        <div className="mt-12 border-t border-slate-800/80 pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between text-[11px] text-slate-500">
            <div>
              <p>
                © {new Date().getFullYear()} AlgoXen Protocol. All rights reserved.
              </p>
              <p className="mt-1 text-slate-500">
                AlgoXen is a simulated trading environment with virtual USDC balances. Nothing here constitutes investment, legal, or financial advice.
              </p>
            </div>

            <div className="flex shrink-0 items-center gap-4 text-slate-400">
              <a
                href={`${docsBase}disclaimers/`}
                target="_blank"
                rel="noopener noreferrer"
                className="transition hover:text-emerald-400"
              >
                Disclaimers
              </a>
              <span className="text-slate-700">•</span>
              <a
                href={`${docsBase}do-dont/`}
                target="_blank"
                rel="noopener noreferrer"
                className="transition hover:text-emerald-400"
              >
                Rules & Integrity
              </a>
              <span className="text-slate-700">•</span>
              <span className="font-mono text-[10px] text-slate-400">
                HMAC-SHA512 / EIP-712 Verified
              </span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  )
}
