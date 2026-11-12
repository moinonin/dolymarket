import React, { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Dolymarket ErrorBoundary caught an unhandled error:', error, errorInfo)
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6 font-geist-mono">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/90 p-6 shadow-2xl backdrop-blur text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 mb-4">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <h2 className="text-base font-bold text-white">Something interrupted the view</h2>
            <p className="mt-2 text-xs text-slate-400 leading-relaxed">
              {this.state.error?.message || 'An unexpected client error or extension conflict occurred.'}
            </p>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-emerald-500 py-2.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 transition"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Reload Application
              </button>
              <button
                type="button"
                onClick={() => this.setState({ hasError: false, error: null })}
                className="flex-1 rounded-xl border border-slate-700 bg-slate-800 py-2.5 text-xs font-semibold text-slate-200 hover:bg-slate-700 transition"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
