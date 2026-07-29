import { useEffect, useState } from 'react'
import { BadgeCheck, CircleDashed, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'
import type { QualityGateKey, QualityMetrics, VoiceCityVersion } from '../../types/voice-city'

interface QualityPanelProps {
  version: VoiceCityVersion | null
  history: Array<Record<string, unknown>>
  onRefresh: () => void | Promise<void>
  onRecord: (metrics: QualityMetrics, durationTestedS: number, notes: string) => void | Promise<void>
}

interface GateDefinition {
  key: QualityGateKey
  label: string
  requirement: string
}

const GATES: GateDefinition[] = [
  { key: 'identity_consistency_30_minutes', label: 'Identity consistency over 30 minutes', requirement: 'Score ≥ 0.85 across at least 30 tested minutes' },
  { key: 'pronunciation_accuracy', label: 'Pronunciation accuracy', requirement: 'Score ≥ 0.95' },
  { key: 'chapter_timbre_stability', label: 'Chapter-to-chapter timbre stability', requirement: 'Score ≥ 0.85' },
  { key: 'emotional_controllability', label: 'Emotional controllability', requirement: 'Score ≥ 0.75' },
  { key: 'no_speaker_drift', label: 'No speaker drift', requirement: 'Zero drift events in the tested audio' },
  { key: 'loudness_consistency', label: 'Loudness consistency', requirement: 'Max chapter loudness delta ≤ 1.5 dB' },
  { key: 'long_form_listening_evaluation', label: 'Long-form listening evaluation', requirement: 'Human long-form listen passed' },
  { key: 'duplicate_similarity_screening', label: 'Duplicate similarity screening', requirement: 'Similarity screen against existing voices passed' },
]

const DEFAULT_METRICS: QualityMetrics = {
  identity_consistency: 0.9,
  pronunciation_accuracy: 0.97,
  chapter_timbre_stability: 0.9,
  emotional_controllability: 0.8,
  speaker_drift_events: 0,
  max_chapter_loudness_delta_db: 0.8,
  long_form_listening_passed: false,
  similarity_screen_passed: false,
}

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null

/** Pulls readiness.checks out of a stored evaluation row. */
function readinessOf(entry: Record<string, unknown> | undefined): { checks: Record<string, boolean> | null; ready: boolean } {
  const metrics = asRecord(entry?.metrics)
  const readiness = asRecord(metrics?.readiness)
  const checksRecord = asRecord(readiness?.checks)
  if (!checksRecord) return { checks: null, ready: false }
  const checks: Record<string, boolean> = {}
  for (const [key, value] of Object.entries(checksRecord)) checks[key] = value === true
  return { checks, ready: readiness?.production_ready === true }
}

const text = (value: unknown): string => (typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '')

export function QualityPanel({ version, history, onRefresh, onRecord }: QualityPanelProps) {
  const [metrics, setMetrics] = useState<QualityMetrics>(DEFAULT_METRICS)
  const [durationMinutes, setDurationMinutes] = useState(35)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void onRefresh()
    // The refresh callback identity changes every render; the version drives refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version?.id])

  const patch = (partial: Partial<QualityMetrics>) => setMetrics(current => ({ ...current, ...partial }))

  const latest = history[0]
  const { checks, ready } = readinessOf(latest)
  const passedCount = checks ? GATES.filter(gate => checks[gate.key]).length : 0

  const record = async () => {
    setSubmitting(true)
    try {
      await onRecord(metrics, Math.max(0, durationMinutes) * 60, notes.trim())
    } finally {
      setSubmitting(false)
    }
  }

  if (!version) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
        <ShieldCheck className="mx-auto mb-2 h-5 w-5 text-slate-400" aria-hidden="true" />
        Select a voice and version to review production-readiness evidence.
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(400px,1fr)_minmax(400px,1fr)]">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-emerald-600" aria-hidden="true" />
            <h2 className="font-semibold">Readiness gates · V{version.version_number}</h2>
          </div>
          {version.status === 'production-ready' || ready ? (
            <span className="flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" /> Production-ready
            </span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600">
              {checks ? `${passedCount}/${GATES.length} gates passed` : 'Not yet evaluated'}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          All eight gates must pass before a version is marked production-ready. Passing every gate promotes the version automatically when the evaluation is recorded.
        </p>
        <ul className="mt-4 space-y-2">
          {GATES.map(gate => {
            const state: 'passed' | 'failed' | 'pending' = checks ? (checks[gate.key] ? 'passed' : 'failed') : 'pending'
            return (
              <li key={gate.key} className={`flex items-start gap-3 rounded-lg p-3 ${state === 'passed' ? 'bg-emerald-50' : state === 'failed' ? 'bg-red-50' : 'bg-slate-50'}`}>
                {state === 'passed' && <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />}
                {state === 'failed' && <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" aria-hidden="true" />}
                {state === 'pending' && <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />}
                <div>
                  <p className="text-sm font-medium text-slate-800">
                    {gate.label}
                    <span className="sr-only"> — {state}</span>
                  </p>
                  <p className="text-[11px] text-slate-500">{gate.requirement}</p>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      <div className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Run an evaluation</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Record measured metrics from your listening session. The server computes the gate report and promotes the version when every gate passes.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {([
              ['identity_consistency', 'Identity consistency (0–1)', 0.01],
              ['pronunciation_accuracy', 'Pronunciation accuracy (0–1)', 0.01],
              ['chapter_timbre_stability', 'Timbre stability (0–1)', 0.01],
              ['emotional_controllability', 'Emotional controllability (0–1)', 0.01],
            ] as const).map(([key, label, step]) => (
              <label key={key} className="text-xs font-medium text-slate-700">
                {label}
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={step}
                  value={metrics[key]}
                  onChange={event => patch({ [key]: Number(event.target.value) } as Partial<QualityMetrics>)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            ))}
            <label className="text-xs font-medium text-slate-700">
              Speaker drift events
              <input
                type="number"
                min={0}
                step={1}
                value={metrics.speaker_drift_events}
                onChange={event => patch({ speaker_drift_events: Math.max(0, Math.round(Number(event.target.value))) })}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs font-medium text-slate-700">
              Max chapter loudness delta (dB)
              <input
                type="number"
                min={0}
                step={0.1}
                value={metrics.max_chapter_loudness_delta_db}
                onChange={event => patch({ max_chapter_loudness_delta_db: Number(event.target.value) })}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs font-medium text-slate-700">
              Minutes of audio tested
              <input
                type="number"
                min={0}
                step={1}
                value={durationMinutes}
                onChange={event => setDurationMinutes(Number(event.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs font-medium text-slate-700">
              Notes
              <input
                value={notes}
                onChange={event => setNotes(event.target.value)}
                placeholder="Session context (optional)"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-3 space-y-2 text-xs text-slate-600">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={metrics.long_form_listening_passed} onChange={event => patch({ long_form_listening_passed: event.target.checked })} className="h-3.5 w-3.5 accent-emerald-600" />
              Long-form listening evaluation passed
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={metrics.similarity_screen_passed} onChange={event => patch({ similarity_screen_passed: event.target.checked })} className="h-3.5 w-3.5 accent-emerald-600" />
              Duplicate similarity screening passed
            </label>
          </div>
          <button
            type="button"
            disabled={submitting}
            onClick={() => { void record() }}
            className="mt-4 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
          >
            {submitting ? 'Recording…' : 'Record evaluation & update gates'}
          </button>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">Evaluation history ({history.length})</h2>
            <button type="button" onClick={() => { void onRefresh() }} aria-label="Refresh evaluation history" className="flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
              <RefreshCw className="h-3 w-3" aria-hidden="true" /> Refresh
            </button>
          </div>
          {!history.length ? (
            <p className="mt-3 rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">No evaluations recorded for this version yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {history.map((entry, index) => {
                const status = text(entry.status) || 'recorded'
                const passed = status === 'passed'
                return (
                  <li key={text(entry.id) || index} className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 p-3 text-xs">
                    <div className="min-w-0">
                      <p className="font-medium text-slate-800">
                        <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${passed ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{status}</span>
                        {text(entry.evaluation_type) || 'production-readiness'}
                      </p>
                      {text(entry.notes) && <p className="mt-1 text-slate-500">{text(entry.notes)}</p>}
                    </div>
                    <span className="shrink-0 text-[10px] text-slate-400">{text(entry.created_at)}</span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
