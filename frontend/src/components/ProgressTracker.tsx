import React from 'react'
import { TaskStatus } from '../types'
import { CheckCircle, XCircle, Loader, Download, AlertTriangle, Database } from 'lucide-react'

interface Props {
  taskStatus: TaskStatus | null
  onDownload: (taskId: string, format: string) => void
}

export const ProgressTracker: React.FC<Props> = ({ taskStatus, onDownload }) => {
  if (!taskStatus) return null

  const isDone = taskStatus.status === 'succeeded' || taskStatus.status === 'completed'
  const needsReview = taskStatus.status === 'needs_review'
  const isFailed = taskStatus.status === 'failed' || taskStatus.status === 'canceled'

  const icon = () => {
    if (isDone) return <CheckCircle className="h-8 w-8 text-green-500" />
    if (needsReview) return <AlertTriangle className="h-8 w-8 text-amber-500" />
    if (isFailed) return <XCircle className="h-8 w-8 text-red-500" />
    return <Loader className="h-8 w-8 text-blue-500 animate-spin" />
  }

  const color = () => {
    if (isDone) return 'text-green-700 bg-green-50 border-green-200'
    if (needsReview) return 'text-amber-700 bg-amber-50 border-amber-200'
    if (isFailed) return 'text-red-700 bg-red-50 border-red-200'
    return 'text-blue-700 bg-blue-50 border-blue-200'
  }

  const active = !isDone && !needsReview && !isFailed
  const cached = taskStatus.cached_chunks || 0
  const synthesized = taskStatus.synthesized_chunks || 0
  const qcIssues = taskStatus.qc_issues || []

  return (
    <div className={`border rounded-lg p-6 ${color()}`}>
      <div className="flex items-center space-x-3 mb-4">
        {icon()}
        <div>
          <h3 className="font-medium capitalize">{taskStatus.status}</h3>
          <p className="text-sm opacity-75">
            {active && taskStatus.chapters_count > 0 && `Chapter ${taskStatus.current_chapter} of ${taskStatus.chapters_count}`}
            {isDone && 'Audiobook ready for download'}
            {needsReview && 'Finished with quality warnings — review before publishing'}
            {isFailed && (taskStatus.error || 'Production did not complete')}
          </p>
        </div>
      </div>

      {active && (
        <div className="space-y-2 mb-4">
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div className="bg-blue-600 h-2 rounded-full transition-all duration-300" style={{ width: `${taskStatus.progress}%` }} />
          </div>
          <div className="flex justify-between text-sm"><span>Progress</span><span>{taskStatus.progress}%</span></div>
        </div>
      )}

      {(cached > 0 || synthesized > 0) && (
        <div className="flex items-center space-x-2 text-sm mb-4 opacity-80">
          <Database className="h-4 w-4" />
          <span>{synthesized} chunks synthesized · {cached} reused from cache</span>
        </div>
      )}

      {taskStatus.chapters && taskStatus.chapters.length > 0 && (
        <div className="mb-4 max-h-48 overflow-y-auto space-y-1">
          {taskStatus.chapters.map((c, i) => (
            <div key={i} className="flex items-center justify-between text-sm py-1 border-b border-black/5 last:border-0">
              <span className="truncate mr-2">{c.title}</span>
              <span className="flex items-center space-x-1 shrink-0">
                {c.status === 'done' && c.qc?.passed && <CheckCircle className="h-4 w-4 text-green-500" />}
                {c.status === 'done' && c.qc && !c.qc.passed && <AlertTriangle className="h-4 w-4 text-amber-500" />}
                {c.status === 'processing' && <Loader className="h-4 w-4 animate-spin text-blue-500" />}
                {c.qc && <span className="text-xs opacity-60">{Math.round(c.qc.duration_s / 60)}m</span>}
              </span>
            </div>
          ))}
        </div>
      )}

      {qcIssues.length > 0 && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-center space-x-2 text-amber-800 font-medium text-sm mb-1">
            <AlertTriangle className="h-4 w-4" /><span>Quality warnings</span>
          </div>
          <ul className="text-xs text-amber-700 space-y-1">
            {qcIssues.map((q, i) => (
              <li key={i}><span className="font-medium">{q.chapter}:</span> {q.issues.join('; ')}</li>
            ))}
          </ul>
        </div>
      )}

      {(isDone || needsReview) && (
        <div className="flex space-x-3">
          {(taskStatus.formats || ['mp3']).map(fmt => (
            <button key={fmt} onClick={() => onDownload(taskStatus.task_id, fmt)}
              className="flex items-center space-x-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
              <Download className="h-4 w-4" />
              <span>{fmt === 'm4b' ? 'M4B (chapters)' : fmt.toUpperCase()}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
