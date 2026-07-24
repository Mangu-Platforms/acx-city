'use client'
import useSWR, { mutate } from 'swr'
import { useState } from 'react'
import { api, Job } from '@/lib/api'
import { StatusBadge, QCBadge } from '@/components/Badges'

const REFRESH = 10_000

function fmt(s: string | undefined) {
  if (!s) return '—'
  return new Date(s).toLocaleString()
}

function JobRow({ job, onAction }: { job: Job; onAction: () => void }) {
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn(); onAction() } finally { setBusy(false) }
  }

  const hasQCFail = job.chapters.some(c => c.qc !== null && !c.qc.passed)

  return (
    <>
      <tr
        className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded(e => !e)}
      >
        <td className="px-4 py-3 font-mono text-xs text-gray-500">{job.job_id.slice(0, 8)}</td>
        <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
        <td className="px-4 py-3 text-sm text-gray-700">{job.provider}</td>
        <td className="px-4 py-3 text-sm text-gray-700">{job.chapters_count}</td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="w-24 bg-gray-100 rounded-full h-1.5">
              <div className="bg-blue-500 h-1.5 rounded-full" style={{ width: `${job.progress}%` }} />
            </div>
            <span className="text-xs text-gray-500">{job.progress}%</span>
          </div>
        </td>
        <td className="px-4 py-3">
          <QCBadge passed={hasQCFail ? false : job.status === 'succeeded' ? true : null} />
        </td>
        <td className="px-4 py-3 text-xs text-gray-400">{job.attempts}</td>
        <td className="px-4 py-3">
          <div className="flex gap-1" onClick={e => e.stopPropagation()}>
            {job.status === 'needs_review' && (
              <>
                <button disabled={busy} onClick={() => act(() => api.approveJob(job.job_id))}
                  className="px-2 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200 disabled:opacity-50">
                  Approve
                </button>
                <button disabled={busy} onClick={() => act(() => api.rejectJob(job.job_id, 'rejected by ops'))}
                  className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50">
                  Reject
                </button>
              </>
            )}
            {(job.status === 'queued' || job.status === 'running') && (
              <button disabled={busy} onClick={() => act(() => api.cancelJob(job.job_id))}
                className="px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded hover:bg-gray-200 disabled:opacity-50">
                Cancel
              </button>
            )}
            {(job.status === 'succeeded' || job.status === 'failed' || job.status === 'canceled') && (
              <button disabled={busy} onClick={() => act(() => api.deleteJob(job.job_id))}
                className="px-2 py-1 text-xs bg-red-50 text-red-500 rounded hover:bg-red-100 disabled:opacity-50">
                Delete
              </button>
            )}
          </div>
        </td>
      </tr>

      {expanded && (
        <tr className="bg-gray-50">
          <td colSpan={8} className="px-4 py-3">
            {job.error && (
              <p className="text-xs text-red-600 mb-2 font-mono bg-red-50 px-2 py-1 rounded">{job.error}</p>
            )}
            {job.chapters.length > 0 && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-400">
                    <th className="pr-4 pb-1">Chapter</th>
                    <th className="pr-4 pb-1">Status</th>
                    <th className="pr-4 pb-1">Duration</th>
                    <th className="pr-4 pb-1">Loudness</th>
                    <th className="pr-4 pb-1">Silence</th>
                    <th className="pr-4 pb-1">Clipping</th>
                    <th className="pb-1">QC</th>
                  </tr>
                </thead>
                <tbody>
                  {job.chapters.map(c => (
                    <tr key={c.index} className="border-t border-gray-100">
                      <td className="pr-4 py-1 text-gray-700">{c.title || `Ch ${c.index + 1}`}</td>
                      <td className="pr-4 py-1 text-gray-500">{c.status}</td>
                      <td className="pr-4 py-1 text-gray-500">{c.qc?.duration_s != null ? `${c.qc.duration_s}s` : '—'}</td>
                      <td className="pr-4 py-1 text-gray-500">{c.qc?.loudness_dbfs != null ? `${c.qc.loudness_dbfs} dB` : '—'}</td>
                      <td className="pr-4 py-1 text-gray-500">{c.qc?.silence_ratio != null ? `${(c.qc.silence_ratio * 100).toFixed(0)}%` : '—'}</td>
                      <td className="pr-4 py-1">{c.qc?.clipping ? <span className="text-red-500">yes</span> : <span className="text-gray-400">no</span>}</td>
                      <td className="py-1"><QCBadge passed={c.qc?.passed ?? null} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function JobsPage() {
  const { data: jobs, isLoading, mutate: reload } = useSWR('jobs', api.jobs, { refreshInterval: REFRESH })
  const [filter, setFilter] = useState<string>('all')

  const filtered = jobs?.filter(j => filter === 'all' || j.status === filter) ?? []

  const STATUSES = ['all', 'running', 'queued', 'needs_review', 'succeeded', 'failed', 'canceled']

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-bold text-gray-900">Jobs</h1>
        <button onClick={() => reload()} className="text-xs text-gray-500 hover:text-gray-800 px-3 py-1.5 border border-gray-200 rounded-lg">
          Refresh
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 flex-wrap mb-4">
        {STATUSES.map(s => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === s ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s}{jobs && s !== 'all' ? ` (${jobs.filter(j => j.status === s).length})` : ''}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-gray-400">Loading jobs…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400">No jobs matching filter.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">ID</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Status</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Provider</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Chapters</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Progress</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">QC</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Attempts</th>
                <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(j => (
                <JobRow key={j.job_id} job={j} onAction={() => reload()} />
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-gray-400 mt-2">Click any row to expand chapter-level QC detail. Auto-refreshes every 10 s.</p>
    </div>
  )
}
