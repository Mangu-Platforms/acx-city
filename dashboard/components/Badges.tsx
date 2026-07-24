import type { JobStatus } from '@/lib/api'

const STATUS_STYLE: Record<JobStatus, string> = {
  queued:       'bg-gray-100 text-gray-600',
  running:      'bg-blue-100 text-blue-700',
  succeeded:    'bg-green-100 text-green-700',
  needs_review: 'bg-yellow-100 text-yellow-700',
  failed:       'bg-red-100 text-red-700',
  canceled:     'bg-gray-100 text-gray-400',
}

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_STYLE[status]}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

export function QCBadge({ passed }: { passed: boolean | null }) {
  if (passed === null) return <span className="text-xs text-gray-400">—</span>
  return passed
    ? <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-700">pass</span>
    : <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700">fail</span>
}
