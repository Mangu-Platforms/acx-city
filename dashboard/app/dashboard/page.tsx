'use client'
import useSWR from 'swr'
import { api, Job, JobStatus } from '@/lib/api'
import { StatCard } from '@/components/StatCard'

const REFRESH = 15_000

function jobsByStatus(jobs: Job[]) {
  const counts: Record<string, number> = {}
  for (const j of jobs) counts[j.status] = (counts[j.status] ?? 0) + 1
  return counts
}

function qcFailRate(jobs: Job[]) {
  const terminal = jobs.filter(j => j.status === 'succeeded' || j.status === 'needs_review')
  if (!terminal.length) return null
  const failed = terminal.filter(j =>
    j.chapters.some(c => c.qc !== null && !c.qc.passed)
  ).length
  return Math.round((failed / terminal.length) * 100)
}

export default function OverviewPage() {
  const { data: jobs, isLoading: jobsLoading } = useSWR('jobs', api.jobs, { refreshInterval: REFRESH })
  const { data: usage, isLoading: usageLoading } = useSWR('usage', api.usage, { refreshInterval: REFRESH })
  const { data: cache } = useSWR('cache', api.cacheStats, { refreshInterval: REFRESH })
  const { data: health } = useSWR('health', api.health, { refreshInterval: REFRESH })

  const counts = jobs ? jobsByStatus(jobs) : {}
  const qcRate = jobs ? qcFailRate(jobs) : null
  const running = counts['running'] ?? 0
  const queued  = counts['queued']  ?? 0
  const failed  = counts['failed']  ?? 0
  const review  = counts['needs_review'] ?? 0

  const cacheMB = cache ? (cache.bytes / 1_048_576).toFixed(1) : '—'

  return (
    <div>
      <h1 className="text-lg font-bold text-gray-900 mb-1">Overview</h1>
      <p className="text-sm text-gray-500 mb-6">
        Live snapshot — refreshes every 15 s
        {health && (
          <span className={`ml-2 inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
            health.status === 'healthy' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
          }`}>{health.status}</span>
        )}
      </p>

      {/* Job queue */}
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Job Queue</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <StatCard label="Running"      value={jobsLoading ? '…' : running} accent={running > 0 ? 'blue' : 'gray'} />
        <StatCard label="Queued"       value={jobsLoading ? '…' : queued}  accent={queued  > 0 ? 'yellow' : 'gray'} />
        <StatCard label="Needs review" value={jobsLoading ? '…' : review}  accent={review  > 0 ? 'yellow' : 'gray'} />
        <StatCard label="Failed"       value={jobsLoading ? '…' : failed}  accent={failed  > 0 ? 'red' : 'gray'} />
      </div>

      {/* Usage + QC */}
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Usage &amp; Quality</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Characters this month"
          value={usageLoading ? '…' : (usage?.characters ?? 0).toLocaleString()}
          sub={usage?.period}
          accent="blue"
        />
        <StatCard
          label="Polly cost (USD)"
          value={usageLoading ? '…' : `$${(usage?.cost_usd ?? 0).toFixed(4)}`}
          sub="paid provider only"
          accent="gray"
        />
        <StatCard
          label="QC fail rate"
          value={qcRate === null ? '—' : `${qcRate}%`}
          sub="terminal jobs"
          accent={qcRate !== null && qcRate > 20 ? 'red' : 'green'}
        />
        <StatCard
          label="Cache"
          value={cache ? `${cache.entries} chunks` : '…'}
          sub={`${cacheMB} MB`}
          accent="gray"
        />
      </div>

      {/* Providers */}
      {health?.providers && (
        <>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">TTS Providers</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-8">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left px-4 py-2 font-semibold text-gray-600">Provider</th>
                  <th className="text-left px-4 py-2 font-semibold text-gray-600">Status</th>
                  <th className="text-left px-4 py-2 font-semibold text-gray-600">Paid</th>
                </tr>
              </thead>
              <tbody>
                {health.providers.map(p => (
                  <tr key={p.name} className="border-b border-gray-50 last:border-0">
                    <td className="px-4 py-2 font-medium text-gray-800">{p.display_name}</td>
                    <td className="px-4 py-2">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
                        p.available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
                      }`}>{p.available ? 'available' : 'unavailable'}</span>
                    </td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{p.paid ? 'yes' : 'free'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
