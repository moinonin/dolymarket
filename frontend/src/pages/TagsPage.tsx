import React, { useEffect, useState } from 'react'
import { Loader2, Tag } from 'lucide-react'
import { api } from '../api/client'
import { Skeleton } from '../components/ui'
import { useToast } from '../context/toast'

export default function TagsPage() {
  const { push } = useToast()
  const [tags, setTags] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await api.listTags()
        if (!cancelled) setTags(res.tags || [])
      } catch (err: any) {
        if (!cancelled) { setError(err?.message || 'Could not load tags'); setTags([]) }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      <h1 className="text-2xl font-bold text-white">Tags</h1>
      <p className="mt-1 text-sm text-slate-400">Browse markets by tag.</p>
      {error && <div className="mt-4 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">{error}</div>}
      {loading ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : (tags || []).length === 0 ? (
        <div className="mt-10 rounded-2xl border border-dashed border-slate-800 py-14 text-center">
          <Tag className="mx-auto mb-3 h-7 w-7 text-slate-600" />
          <p className="text-sm font-medium text-slate-300">No tags yet</p>
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap gap-2">
          {(tags || []).map((t) => (
            <span key={t} className="rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1 text-xs text-slate-200">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}