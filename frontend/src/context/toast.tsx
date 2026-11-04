import React, { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'

export interface Toast {
  id: number
  message: string
  kind: 'error' | 'info'
}

interface ToastContextValue {
  push: (message: string, kind?: 'error' | 'info') => void
}

const ToastContext = createContext<ToastContextValue>({ push: () => {} })

let idCounter = 0

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, kind: 'error' | 'info' = 'info') => {
    const id = ++idCounter
    setToasts((prev) => [...prev, { id, message, kind }])
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 5000)
  }, [])

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm shadow-lg backdrop-blur transition-all ${
              t.kind === 'error'
                ? 'border-red-800/60 bg-red-950/90 text-red-100'
                : 'border-emerald-800/60 bg-emerald-950/90 text-emerald-100'
            }`}
          >
            {t.kind === 'error' ? (
              <XCircle className="h-4 w-4 shrink-0" />
            ) : (
              <CheckCircle2 className="h-4 w-4 shrink-0" />
            )}
            <span className="leading-snug">{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
