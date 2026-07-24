import { ReactNode } from 'react'

interface Props {
  label: string
  value: string | number
  sub?: string
  accent?: 'blue' | 'green' | 'yellow' | 'red' | 'gray'
  icon?: ReactNode
}

const ACCENT = {
  blue:   'bg-blue-50 text-blue-700 border-blue-100',
  green:  'bg-green-50 text-green-700 border-green-100',
  yellow: 'bg-yellow-50 text-yellow-700 border-yellow-100',
  red:    'bg-red-50 text-red-700 border-red-100',
  gray:   'bg-gray-50 text-gray-600 border-gray-100',
}

export function StatCard({ label, value, sub, accent = 'gray', icon }: Props) {
  return (
    <div className={`rounded-xl border p-5 ${ACCENT[accent]}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
        {icon && <span className="opacity-60">{icon}</span>}
      </div>
      <p className="mt-2 text-2xl font-bold tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs opacity-60">{sub}</p>}
    </div>
  )
}
