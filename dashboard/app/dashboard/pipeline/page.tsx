'use client'

// Pipeline observability (P1.7 rebuild). Observational only: this page
// renders what /api/ops/pipeline and /api/jobs/:id/stages report and takes
// no actions. Built exclusively on the canonical typed client — no generic
// HTTP helpers.

import React, { useCallback, useEffect, useState } from 'react'
import {
  Activity, AlertTriangle, Archive, CheckCircle2, ChevronDown, ChevronRight,
  Clock, Database, HardDrive, RefreshCw, Server, XCircle,
} from 'lucide-react'
import { api, ApiError, PipelineOverview, StageRecord } from '../../../lib/api'

const POLL_MS = 10_000

function Tile({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'ok' | 'warn' | 'bad' }) {
  const toneCls =
    tone === 'bad' ? 'text-red-600' : tone === 'warn' ? 'text-amber-600' : 'text-slate-900'
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneCls}`}>{value}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    succeeded: 'bg-green-100 text-green-800',
    running: 'bg-blue-100 text-blue-800',
    queued: 'bg-slate-100 text-slate-700',
    needs_review: 'bg-amber-100 text-amber-800',
    failed: 'bg-red-100 text-red-800',
    canceled: 'bg-slate-200 text-slate-600',
  }
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls[status] ?? 'bg-slate-100 text-slate-700'}`}>
      {status}
    </span>
  )
}

function StageTimeline({ jobId }: { jobId: string }) {
  const [stages, setStages] = useState<StageRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.jobStages(jobId)
      .then((r) => setStages(r.stages))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'failed to load'))
  }, [jobId])

  if (error) return <div className="p-3 text-sm text-red-600">{error}</div>
  if (!stages) return <div className="p-3 text-sm text-slate-500">Loading stages…</div>
  if (!stages.length) return <div className="p-3 text-sm text-slate-500">No stage records.</div>

  const byChapter = new Map<number, StageRecord[]>()
  stages.forEach((s) => {
    const list = byChapter.get(s.chapter_index) ?? []
    list.push(s)
    byChapter.set(s.chapter_index, list)
  })

  return (
    <div className="space-y-2 p-3">
      {[...byChapter.entries()].map(([chapter, records]) => (
        <div key={chapter} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-slate-500">ch {chapter}</span>
          {records.map((r, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3 text-slate-400" />}
              <span
                className="rounded bg-slate-100 px-2 py-0.5 text-xs"
                title={new Date(r.completed_at).toLocaleString()}
              >
                {r.stage}
              </span>
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

export default function PipelinePage() {
  const [data, setData] = useState<PipelineOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const overview = await api.pipelineOverview()
      setData(overview)
      setError(null)
      setUpdatedAt(new Date())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load pipeline state')
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [load])

  if (error && !data) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-2 text-red-600">
          <XCircle className="h-5 w-5" /> {error}
        </div>
      </div>
    )
  }
  if (!data) return <div className="p-8 text-slate-500">Loading pipeline…</div>

  const staleWorkers = data.workers.filter((w) => w.stale).length

  return (
    <div className="space-y-8 p-8">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Activity className="h-6 w-6" /> Pipeline
        </h1>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <RefreshCw className="h-3 w-3" />
          {updatedAt ? `updated ${updatedAt.toLocaleTimeString()}` : ''}
          {error && <span className="text-amber-600">(refresh failed: {error})</span>}
        </div>
      </div>

      {/* Queue + throughput tiles */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
        <Tile label="Queued" value={data.queue.queued} />
        <Tile label="Running" value={data.queue.running} />
        <Tile label="Stuck" value={data.queue.stuck} tone={data.queue.stuck ? 'bad' : 'ok'} />
        <Tile label="Needs review" value={data.queue.needs_review} tone={data.queue.needs_review ? 'warn' : 'ok'} />
        <Tile label="Failed jobs" value={data.queue.failed} tone={data.queue.failed ? 'warn' : 'ok'} />
        <Tile
          label="Cache hit rate"
          value={data.cache_hit_rate === null ? '—' : `${Math.round(data.cache_hit_rate * 100)}%`}
        />
        <Tile
          label="Avg job time"
          value={data.avg_job_duration_s === null ? '—' : `${data.avg_job_duration_s}s`}
        />
      </div>

      {/* Health row: workers, providers, storage, QC */}
      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded-lg border border-slate-200 bg-white">
          <header className="flex items-center gap-2 border-b border-slate-100 p-3 font-medium">
            <Server className="h-4 w-4" /> Workers
            {staleWorkers > 0 && (
              <span className="ml-auto flex items-center gap-1 text-xs text-red-600">
                <AlertTriangle className="h-3 w-3" /> {staleWorkers} stale
              </span>
            )}
          </header>
          <div className="p-3 text-sm">
            {data.workers.length === 0 && (
              <div className="text-slate-500">No worker heartbeats recorded.</div>
            )}
            {data.workers.map((w) => (
              <div key={w.worker_id} className="flex items-center justify-between py-1">
                <span className="font-mono text-xs">{w.worker_id}</span>
                <span className={w.stale ? 'text-red-600' : 'text-green-700'}>
                  {w.stale ? `stale ${w.age_s}s` : `${w.age_s}s ago`}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white">
          <header className="flex items-center gap-2 border-b border-slate-100 p-3 font-medium">
            <Database className="h-4 w-4" /> Providers & storage
          </header>
          <div className="space-y-1 p-3 text-sm">
            {data.providers.map((p) => (
              <div key={p.name} className="flex items-center justify-between py-0.5">
                <span>{p.display_name}{p.paid ? ' · paid' : ''}</span>
                {p.available
                  ? <CheckCircle2 className="h-4 w-4 text-green-600" />
                  : <XCircle className="h-4 w-4 text-slate-400" />}
              </div>
            ))}
            <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
              <span className="flex items-center gap-1">
                <HardDrive className="h-4 w-4" /> Storage ({data.storage.backend})
              </span>
              {data.storage.ok
                ? <CheckCircle2 className="h-4 w-4 text-green-600" />
                : <XCircle className="h-4 w-4 text-red-600" />}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white">
          <header className="flex items-center gap-2 border-b border-slate-100 p-3 font-medium">
            <AlertTriangle className="h-4 w-4" /> Quality
          </header>
          <div className="space-y-2 p-3 text-sm">
            <div className="flex justify-between">
              <span>Failed chapters</span>
              <span className={data.failed_chapters ? 'font-semibold text-red-600' : ''}>
                {data.failed_chapters}
              </span>
            </div>
            <div className="flex justify-between">
              <span>QC failures</span>
              <span className={data.qc_failures ? 'font-semibold text-amber-600' : ''}>
                {data.qc_failures}
              </span>
            </div>
          </div>
        </section>
      </div>

      {/* Recent jobs with expandable stage timeline */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <header className="flex items-center gap-2 border-b border-slate-100 p-3 font-medium">
          <Clock className="h-4 w-4" /> Recent jobs
        </header>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="p-2" />
              <th className="p-2">Job</th>
              <th className="p-2">Status</th>
              <th className="p-2">Progress</th>
              <th className="p-2">Attempts</th>
              <th className="p-2">Provider</th>
              <th className="p-2">Chunks (cached/synth)</th>
              <th className="p-2">Updated</th>
            </tr>
          </thead>
          <tbody>
            {data.recent_jobs.map((j) => (
              <React.Fragment key={j.job_id}>
                <tr
                  className="cursor-pointer border-b border-slate-50 hover:bg-slate-50"
                  onClick={() => setExpanded(expanded === j.job_id ? null : j.job_id)}
                >
                  <td className="p-2">
                    {expanded === j.job_id
                      ? <ChevronDown className="h-4 w-4 text-slate-400" />
                      : <ChevronRight className="h-4 w-4 text-slate-400" />}
                  </td>
                  <td className="p-2 font-mono text-xs">{j.job_id.slice(0, 8)}…</td>
                  <td className="p-2"><StatusBadge status={j.status} /></td>
                  <td className="p-2">{j.progress}%</td>
                  <td className="p-2">{j.attempts}</td>
                  <td className="p-2">{j.provider}</td>
                  <td className="p-2">{j.cached_chunks}/{j.synthesized_chunks}</td>
                  <td className="p-2 text-xs text-slate-500">
                    {new Date(j.updated_at).toLocaleTimeString()}
                  </td>
                </tr>
                {j.error && (
                  <tr className="border-b border-slate-50">
                    <td />
                    <td colSpan={7} className="p-2 text-xs text-red-600">{j.error}</td>
                  </tr>
                )}
                {expanded === j.job_id && (
                  <tr className="border-b border-slate-50 bg-slate-50/50">
                    <td />
                    <td colSpan={7}><StageTimeline jobId={j.job_id} /></td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            {data.recent_jobs.length === 0 && (
              <tr><td colSpan={8} className="p-4 text-center text-slate-500">No jobs yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {/* Recent exports */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <header className="flex items-center gap-2 border-b border-slate-100 p-3 font-medium">
          <Archive className="h-4 w-4" /> Recent exports
        </header>
        <div className="p-3 text-sm">
          {data.recent_exports.length === 0 && (
            <div className="text-slate-500">No exports yet.</div>
          )}
          {data.recent_exports.map((e) => (
            <div key={e.job_id} className="flex items-center justify-between py-1">
              <span className="font-mono text-xs">{e.job_id.slice(0, 8)}…</span>
              <span className="text-xs">{e.formats.join(', ')}</span>
              <span className="text-xs text-slate-500">
                {new Date(e.updated_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
