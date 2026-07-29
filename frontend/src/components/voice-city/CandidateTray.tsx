import { useMemo, useState } from 'react'
import { AlertTriangle, Ban, Check, Play, Scale, Sparkles, VenetianMask, X } from 'lucide-react'
import type { VoiceCityCandidate } from '../../types/voice-city'

interface CandidateTrayProps {
  candidates: VoiceCityCandidate[]
  selectedCandidateId: string | null
  onSelect: (candidate: VoiceCityCandidate) => void
  onPreview: (candidate: VoiceCityCandidate) => void
  onAccept: (candidate: VoiceCityCandidate) => void | Promise<void>
  onReject: (candidate: VoiceCityCandidate) => void | Promise<void>
  onCompare: (candidates: VoiceCityCandidate[], blind: boolean) => void | Promise<void>
}

const scoreEntries = (candidate: VoiceCityCandidate): Array<[string, number]> => [
  ['Quality', candidate.quality_score],
  ['Consistency', candidate.consistency_score],
  ['Uniqueness', candidate.uniqueness_score],
]

export function CandidateTray({ candidates, selectedCandidateId, onSelect, onPreview, onAccept, onReject, onCompare }: CandidateTrayProps) {
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set())

  const compareSelection = useMemo(
    () => candidates.filter(candidate => compareIds.has(candidate.id)),
    [candidates, compareIds],
  )
  const compareReady = compareSelection.length >= 2 && compareSelection.length <= 8

  const toggleCompare = (candidateId: string) => {
    setCompareIds(current => {
      const next = new Set(current)
      if (next.has(candidateId)) next.delete(candidateId)
      else next.add(candidateId)
      return next
    })
  }

  if (!candidates.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
        <Sparkles className="mx-auto mb-2 h-5 w-5 text-fuchsia-400" aria-hidden="true" />
        Describe a voice and generate variants to fill the candidate tray.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <span>{compareSelection.length ? `${compareSelection.length} marked for comparison` : 'Mark 2–8 candidates to compare'}</span>
        <div className="flex gap-1.5">
          <button
            type="button"
            disabled={!compareReady}
            onClick={() => { void onCompare(compareSelection, false) }}
            className="flex items-center gap-1 rounded bg-slate-950 px-2 py-1 font-semibold text-white disabled:opacity-30"
          >
            <Scale className="h-3 w-3" aria-hidden="true" /> A/B
          </button>
          <button
            type="button"
            disabled={!compareReady}
            onClick={() => { void onCompare(compareSelection, true) }}
            className="flex items-center gap-1 rounded bg-violet-600 px-2 py-1 font-semibold text-white disabled:opacity-30"
          >
            <VenetianMask className="h-3 w-3" aria-hidden="true" /> Blind
          </button>
        </div>
      </div>

      {candidates.map(candidate => {
        const selected = candidate.id === selectedCandidateId
        const blocked = candidate.status === 'blocked'
        return (
          <article
            key={candidate.id}
            className={`rounded-xl border p-3 transition-colors ${
              blocked
                ? 'border-red-200 bg-red-50'
                : selected
                  ? 'border-cyan-400 bg-cyan-50/60 ring-1 ring-cyan-300'
                  : 'border-slate-200 bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <button type="button" onClick={() => onSelect(candidate)} className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm font-semibold text-slate-900">{candidate.name}</p>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  {candidate.provider} · #{candidate.ordinal + 1}
                </p>
              </button>
              <label className="flex shrink-0 items-center gap-1 text-[10px] text-slate-500">
                <input
                  type="checkbox"
                  checked={compareIds.has(candidate.id)}
                  onChange={() => toggleCompare(candidate.id)}
                  aria-label={`Include ${candidate.name} in comparison`}
                  className="h-3.5 w-3.5 accent-violet-600"
                />
                Compare
              </label>
            </div>

            <div className="mt-2 grid grid-cols-3 gap-1.5">
              {scoreEntries(candidate).map(([label, score]) => (
                <div key={label} className="rounded bg-slate-100 px-1.5 py-1 text-center">
                  <p className="text-[9px] uppercase tracking-wide text-slate-500">{label}</p>
                  <p className="text-xs font-semibold text-slate-800">{Math.round(score * 100)}%</p>
                </div>
              ))}
            </div>

            {blocked && (
              <p className="mt-2 flex items-center gap-1.5 rounded bg-red-100 px-2 py-1.5 text-[11px] font-medium text-red-800">
                <Ban className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                Blocked by protected-profile similarity screening.
              </p>
            )}
            {candidate.warnings.map(warning => (
              <p key={warning} className="mt-1.5 flex items-start gap-1.5 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
                {warning}
              </p>
            ))}
            {candidate.status === 'accepted' && (
              <p className="mt-2 rounded bg-emerald-100 px-2 py-1 text-[11px] font-medium text-emerald-800">Accepted as an immutable version</p>
            )}
            {candidate.status === 'rejected' && (
              <p className="mt-2 rounded bg-slate-100 px-2 py-1 text-[11px] text-slate-500">Rejected</p>
            )}

            <div className="mt-2 flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onPreview(candidate)}
                className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                <Play className="h-3 w-3" aria-hidden="true" /> Preview
              </button>
              <button
                type="button"
                disabled={blocked || candidate.status === 'accepted'}
                onClick={() => { void onAccept(candidate) }}
                aria-label={`Accept ${candidate.name}`}
                className="flex items-center gap-1 rounded-lg bg-emerald-600 px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-30"
              >
                <Check className="h-3 w-3" aria-hidden="true" /> Accept
              </button>
              <button
                type="button"
                onClick={() => { void onReject(candidate) }}
                aria-label={`Reject ${candidate.name}`}
                className="rounded-lg border border-slate-300 p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          </article>
        )
      })}
    </div>
  )
}
