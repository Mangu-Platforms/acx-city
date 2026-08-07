'use client'
import useSWR from 'swr'
import { useState } from 'react'
import { api, ApiError, PipelineTrace } from '@/lib/api'
import { StatCard } from '@/components/StatCard'

const REFRESH = 10_000

function fmtMs(ms: number | null) {
  return ms != null ? `${ms}ms` : '—'
}

function TraceStatus({ status }: { status: string }) {
  const style =
    status === 'completed' ? 'bg-green-100 text-green-700' :
    status === 'failed' ? 'bg-red-100 text-red-700' :
    status === 'running' ? 'bg-amber-100 text-amber-700' :
    'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${style}`}>
      {status}
    </span>
  )
}

function TraceRow({ trace }: { trace: PipelineTrace }) {
  return (
    <tr className="border-b border-gray-50 hover:bg-gray-50">
      <td className="px-4 py-3 font-medium text-sm text-gray-700">{trace.chapter_number}</td>
      <td className="px-4 py-3"><TraceStatus status={trace.status} /></td>
      <td className="px-4 py-3 text-sm">
        {trace.qa_passed === true ? <span className="text-green-600">Pass</span>
          : trace.qa_passed === false ? <span className="text-red-600">Fail</span>
          : <span className="text-gray-400">—</span>}
      </td>
      <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{fmtMs(trace.agent1_ms)}</td>
      <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{fmtMs(trace.agent2_ms)}</td>
      <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{fmtMs(trace.agent3_ms)}</td>
      <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{fmtMs(trace.agent4_ms)}</td>
      <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{fmtMs(trace.agent5_ms)}</td>
      <td className="px-4 py-3 text-right text-sm">
        {trace.qa_completeness_score != null ? (
          <span className={trace.qa_completeness_score > 0.9 ? 'text-green-600' : 'text-amber-600'}>
            {(trace.qa_completeness_score * 100).toFixed(0)}%
          </span>
        ) : <span className="text-gray-400">—</span>}
      </td>
    </tr>
  )
}

export default function PipelinePage() {
  const [selectedProject, setSelectedProject] = useState('')

  const { data: jobs } = useSWR('jobs', api.jobs, { refreshInterval: REFRESH })
  const projectIds = [...new Set((jobs ?? []).map(j => j.project_id))]

  const projectId = selectedProject || projectIds[0] || ''
  const { data: status, error, isLoading, mutate } = useSWR(
    projectId ? ['pipeline-status', projectId] : null,
    () => api.pipelineStatus(projectId),
    { refreshInterval: REFRESH },
  )

  // The sidecar 404s when a project has no pipeline runs — that's "no data", not an error.
  const noData = error instanceof ApiError && error.status === 404

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Pipeline</h1>
          <p className="text-xs text-gray-400">Multi-agent preprocessing traces per chapter</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={projectId}
            onChange={e => setSelectedProject(e.target.value)}
            className="text-xs text-gray-700 px-3 py-1.5 border border-gray-200 rounded-lg bg-white"
          >
            {projectIds.length === 0 && <option value="">No projects</option>}
            {projectIds.map(id => (
              <option key={id} value={id}>{id.slice(0, 8)}…</option>
            ))}
          </select>
          <button onClick={() => mutate()} className="text-xs text-gray-500 hover:text-gray-800 px-3 py-1.5 border border-gray-200 rounded-lg">
            Refresh
          </button>
        </div>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && !noData && <p className="text-sm text-red-500">Pipeline API unreachable — the /v1 sidecar may not be deployed.</p>}

      {status && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Status"
              value={status.status}
              accent={status.status === 'succeeded' ? 'green' : status.status === 'failed' ? 'red' : 'blue'}
            />
            <StatCard
              label="Chapters completed"
              value={`${status.chapters_completed}/${status.chapters_total}`}
              accent="green"
            />
            <StatCard
              label="Chapters failed"
              value={status.chapters_failed}
              accent={status.chapters_failed > 0 ? 'red' : 'gray'}
            />
            <StatCard
              label="Pipeline cost"
              value={`$${status.total_cost_usd.toFixed(4)}`}
              sub="Agents 2–5, all chapters"
              accent="blue"
            />
          </div>

          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Chapter traces</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                  <th className="px-4 py-3 font-medium">Ch</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">QA</th>
                  <th className="px-4 py-3 font-medium text-right">Agent 1</th>
                  <th className="px-4 py-3 font-medium text-right">Agent 2</th>
                  <th className="px-4 py-3 font-medium text-right">Agent 3</th>
                  <th className="px-4 py-3 font-medium text-right">Agent 4</th>
                  <th className="px-4 py-3 font-medium text-right">Agent 5</th>
                  <th className="px-4 py-3 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {status.traces.map(t => <TraceRow key={t.chapter_number} trace={t} />)}
              </tbody>
            </table>
            {status.traces.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-gray-400">No chapter traces yet.</p>
            )}
          </div>
        </>
      )}

      {(noData || (!projectId && jobs)) && !status && (
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-12 text-center text-gray-400">
          <p className="text-sm font-medium text-gray-500">No pipeline data</p>
          <p className="mt-1 text-xs">Run the multi-agent pipeline on a project to see per-chapter traces here.</p>
        </div>
      )}
    </div>
  )
}
