'use client'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { StatCard } from '@/components/StatCard'

const REFRESH = 20_000

export default function HealthPage() {
  const { data, isLoading, error, mutate } = useSWR('health', api.health, { refreshInterval: REFRESH })

  const dbOk = data?.database === 'ok'
  const healthy = data?.status === 'healthy'

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-bold text-gray-900">System Health</h1>
        <button onClick={() => mutate()} className="text-xs text-gray-500 hover:text-gray-800 px-3 py-1.5 border border-gray-200 rounded-lg">
          Refresh
        </button>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Checking…</p>}
      {error && <p className="text-sm text-red-500">Backend unreachable — check Railway deployment and CORS settings.</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
            <StatCard
              label="API"
              value={healthy ? 'Healthy' : 'Degraded'}
              accent={healthy ? 'green' : 'red'}
            />
            <StatCard
              label="Database"
              value={dbOk ? 'Connected' : 'Unreachable'}
              sub="PostgreSQL"
              accent={dbOk ? 'green' : 'red'}
            />
            <StatCard
              label="Providers available"
              value={data.providers.filter(p => p.available).length}
              sub={`of ${data.providers.length} configured`}
              accent="blue"
            />
          </div>

          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">TTS Providers</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-8">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-left">
                  <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Provider</th>
                  <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Available</th>
                  <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Paid</th>
                  <th className="px-4 py-2 font-semibold text-gray-600 text-xs">Max chars / chunk</th>
                </tr>
              </thead>
              <tbody>
                {data.providers.map(p => (
                  <tr key={p.name} className="border-b border-gray-50 last:border-0">
                    <td className="px-4 py-3 font-medium text-gray-800">{p.display_name}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
                        p.available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
                      }`}>{p.available ? 'yes' : 'no'}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{p.paid ? 'paid' : 'free'}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Integration Checklist</h2>
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {[
              { label: 'Railway backend deployed', ok: healthy },
              { label: 'PostgreSQL connected', ok: dbOk },
              { label: 'Edge TTS available (free)', ok: data.providers.find(p => p.name === 'edge')?.available ?? false },
              { label: 'AWS Polly configured', ok: data.providers.find(p => p.name === 'polly')?.available ?? false },
              { label: 'NEXT_PUBLIC_API_URL set', ok: !!process.env.NEXT_PUBLIC_API_URL },
            ].map(item => (
              <div key={item.label} className="flex items-center justify-between px-4 py-3">
                <span className="text-sm text-gray-700">{item.label}</span>
                <span className={`text-xs font-semibold ${item.ok ? 'text-green-600' : 'text-gray-400'}`}>
                  {item.ok ? '✓ ok' : '○ not set'}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
