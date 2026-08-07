import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../lib/api'
import { Activity, CheckCircle, XCircle, Clock, DollarSign, Cpu, Zap } from 'lucide-react'

interface PipelineTrace {
  chapter_number: number
  status: string
  current_agent: string | null
  agent1_ms: number | null
  agent2_ms: number | null
  agent3_ms: number | null
  agent4_ms: number | null
  agent5_ms: number | null
  qa_passed: boolean | null
  qa_completeness_score: number | null
  error: string | null
}

interface PipelineStatus {
  job_id: string
  status: string
  chapters_total: number
  chapters_completed: number
  chapters_failed: number
  total_cost_usd: number
  traces: PipelineTrace[]
}

export default function PipelinePage() {
  const [projects, setProjects] = useState<any[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // Fetch projects from the API
    api.get('/api/jobs').then(res => {
      const jobs = res.data?.jobs || []
      const uniqueProjects = [...new Map(jobs.map((j: any) => [j.project_id, j])).values()]
      setProjects(uniqueProjects)
      if (uniqueProjects.length > 0) setSelectedProject(uniqueProjects[0].project_id)
    }).catch(() => {})
  }, [])

  const fetchStatus = useCallback(async () => {
    if (!selectedProject) return
    setLoading(true)
    try {
      const res = await api.get(`/v1/projects/${selectedProject}/pipeline/status`)
      setPipelineStatus(res.data)
    } catch {
      setPipelineStatus(null)
    } finally {
      setLoading(false)
    }
  }, [selectedProject])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed': return <XCircle className="h-4 w-4 text-red-500" />
      case 'running': return <Clock className="h-4 w-4 text-amber-500 animate-pulse" />
      default: return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  const formatMs = (ms: number | null) => ms != null ? `${ms}ms` : '—'
  const formatCost = (usd: number) => `$${usd.toFixed(4)}`

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline Status</h1>
          <p className="text-sm text-gray-500">Multi-agent preprocessing pipeline traces</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedProject}
            onChange={e => setSelectedProject(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">Select project...</option>
            {projects.map((p: any) => (
              <option key={p.project_id} value={p.project_id}>
                {p.project_id?.slice(0, 8)}...
              </option>
            ))}
          </select>
          <button onClick={fetchStatus} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
            Refresh
          </button>
        </div>
      </div>

      {pipelineStatus && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-500"><Activity className="h-4 w-4" /> Status</div>
              <div className="mt-1 text-2xl font-bold capitalize">{pipelineStatus.status}</div>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-500"><CheckCircle className="h-4 w-4" /> Completed</div>
              <div className="mt-1 text-2xl font-bold text-green-600">{pipelineStatus.chapters_completed}/{pipelineStatus.chapters_total}</div>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-500"><XCircle className="h-4 w-4" /> Failed</div>
              <div className="mt-1 text-2xl font-bold text-red-600">{pipelineStatus.chapters_failed}</div>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-500"><DollarSign className="h-4 w-4" /> Total Cost</div>
              <div className="mt-1 text-2xl font-bold">{formatCost(pipelineStatus.total_cost_usd)}</div>
            </div>
          </div>

          {/* Chapter Traces */}
          <div className="rounded-lg border bg-white shadow-sm">
            <div className="border-b px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">Chapter Traces</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-500">Ch</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-500">QA</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Agent 1</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Agent 2</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Agent 3</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Agent 4</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Agent 5</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {pipelineStatus.traces.map(trace => (
                    <tr key={trace.chapter_number} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{trace.chapter_number}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {getStatusIcon(trace.status)}
                          <span className="capitalize">{trace.status}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {trace.qa_passed === true ? (
                          <span className="text-green-600">Pass</span>
                        ) : trace.qa_passed === false ? (
                          <span className="text-red-600">Fail</span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{formatMs(trace.agent1_ms)}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{formatMs(trace.agent2_ms)}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{formatMs(trace.agent3_ms)}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{formatMs(trace.agent4_ms)}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{formatMs(trace.agent5_ms)}</td>
                      <td className="px-4 py-3 text-right">
                        {trace.qa_completeness_score != null ? (
                          <span className={trace.qa_completeness_score > 0.9 ? 'text-green-600' : 'text-amber-600'}>
                            {(trace.qa_completeness_score * 100).toFixed(0)}%
                          </span>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {!pipelineStatus && !loading && (
        <div className="rounded-lg border bg-white p-12 text-center text-gray-500">
          <Cpu className="mx-auto mb-4 h-12 w-12 text-gray-300" />
          <p className="text-lg font-medium">No pipeline data</p>
          <p className="mt-1 text-sm">Select a project and run the pipeline to see traces here.</p>
        </div>
      )}
    </div>
  )
}
