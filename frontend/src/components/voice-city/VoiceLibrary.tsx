import { useState } from 'react'
import { Ban, Download, History, Library, Loader2, Plus, Rocket, Trash2, Zap } from 'lucide-react'
import type {
  VoiceCityGenerationJob,
  VoiceCitySelection,
  VoiceCityVersion,
  VoiceCityVoice,
  VoiceCityVoiceStatus,
} from '../../types/voice-city'

interface VoiceLibraryProps {
  voices: VoiceCityVoice[]
  selectedVoiceId: string | null
  busy: boolean
  optimizationEnabled: boolean
  optimizationJob: VoiceCityGenerationJob | null
  onSelect: (voice: VoiceCityVoice) => void | Promise<void>
  onCreate: (name: string) => void | Promise<void>
  onRollback: (voice: VoiceCityVoice, version: VoiceCityVersion) => void | Promise<void>
  onOptimize: (version: VoiceCityVersion) => void | Promise<void>
  onCancelOptimization: (job: VoiceCityGenerationJob) => void | Promise<void>
  onUse: (selection: VoiceCitySelection) => void
  onExport: (voice: VoiceCityVoice) => void | Promise<void>
  onRevoke: (voice: VoiceCityVoice) => void | Promise<void>
  onDelete: (voice: VoiceCityVoice) => void | Promise<void>
}

const STATUS_BADGE: Record<VoiceCityVoiceStatus, string> = {
  draft: 'bg-amber-100 text-amber-800',
  ready: 'bg-emerald-100 text-emerald-800',
  revoked: 'bg-red-100 text-red-700',
  deleted: 'bg-slate-200 text-slate-500',
}

function selectionFor(voice: VoiceCityVoice, version: VoiceCityVersion): VoiceCitySelection {
  return {
    voiceId: voice.id,
    voiceVersionId: version.id,
    provider: version.provider || voice.provider,
    providerVoiceId: version.provider_voice_id || '',
    displayName: voice.name,
    versionNumber: version.version_number,
    seed: version.seed,
  }
}

function versionsOf(voice: VoiceCityVoice): VoiceCityVersion[] {
  if (voice.versions?.length) return voice.versions
  return voice.current_version ? [voice.current_version] : []
}

export function VoiceLibrary({
  voices,
  selectedVoiceId,
  busy,
  optimizationEnabled,
  optimizationJob,
  onSelect,
  onCreate,
  onRollback,
  onOptimize,
  onCancelOptimization,
  onUse,
  onExport,
  onRevoke,
  onDelete,
}: VoiceLibraryProps) {
  const [newName, setNewName] = useState('')
  const jobActive = Boolean(optimizationJob && ['queued', 'running'].includes(optimizationJob.status))

  const create = () => {
    const name = newName.trim()
    if (!name) return
    setNewName('')
    void onCreate(name)
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={event => { event.preventDefault(); create() }}
        className="flex gap-1.5"
      >
        <label className="min-w-0 flex-1">
          <span className="sr-only">New voice name</span>
          <input
            value={newName}
            onChange={event => setNewName(event.target.value)}
            placeholder="Name a new voice from current controls"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !newName.trim()}
          aria-label="Create voice with an immutable V1"
          className="flex items-center gap-1 rounded-lg bg-slate-950 px-2.5 py-2 text-xs font-semibold text-white disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Create
        </button>
      </form>

      {optimizationJob && jobActive && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs text-violet-900">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 font-semibold">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              Identity optimization {optimizationJob.status}
              {optimizationJob.stage ? ` · ${optimizationJob.stage}` : ''}
            </span>
            <button
              type="button"
              onClick={() => { void onCancelOptimization(optimizationJob) }}
              className="rounded border border-violet-300 px-2 py-0.5 font-semibold hover:bg-violet-100"
            >
              Cancel
            </button>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-violet-200">
            <div className="h-full rounded-full bg-violet-600 transition-all" style={{ width: `${Math.max(4, Math.min(100, optimizationJob.progress))}%` }} />
          </div>
        </div>
      )}
      {optimizationJob?.status === 'failed' && optimizationJob.error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-[11px] text-red-800">{optimizationJob.error}</p>
      )}

      {!voices.length && (
        <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          <Library className="mx-auto mb-2 h-5 w-5 text-slate-400" aria-hidden="true" />
          No saved voices yet. Accept a candidate or create a voice from the current controls.
        </div>
      )}

      {voices.map(voice => {
        const selected = voice.id === selectedVoiceId
        const revoked = voice.status === 'revoked'
        const versions = versionsOf(voice)
        return (
          <article
            key={voice.id}
            className={`rounded-xl border p-3 ${selected ? 'border-cyan-400 bg-cyan-50/50 ring-1 ring-cyan-300' : 'border-slate-200 bg-white hover:border-slate-300'}`}
          >
            <div className="flex items-start justify-between gap-2">
              <button type="button" onClick={() => { void onSelect(voice) }} className="min-w-0 flex-1 text-left" aria-label={`Open ${voice.name} in the editor`}>
                <p className="truncate text-sm font-semibold text-slate-900">{voice.name}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
                  <span className={`rounded-full px-1.5 py-0.5 font-semibold uppercase tracking-wide ${STATUS_BADGE[voice.status] || 'bg-slate-100 text-slate-600'}`}>{voice.status}</span>
                  <span className="rounded-full bg-slate-100 px-1.5 py-0.5">{voice.provider}</span>
                  {voice.current_version && <span>V{voice.current_version.version_number}</span>}
                </p>
              </button>
              <div className="flex shrink-0 items-center gap-1">
                <button type="button" onClick={() => { void onExport(voice) }} aria-label={`Export ${voice.name} recipe`} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                  <Download className="h-3.5 w-3.5" />
                </button>
                {!revoked && (
                  <button type="button" onClick={() => { void onRevoke(voice) }} aria-label={`Revoke ${voice.name}`} className="rounded p-1 text-slate-400 hover:bg-amber-50 hover:text-amber-700">
                    <Ban className="h-3.5 w-3.5" />
                  </button>
                )}
                <button type="button" onClick={() => { void onDelete(voice) }} aria-label={`Delete ${voice.name}`} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {voice.tags.length > 0 && (
              <p className="mt-1.5 flex flex-wrap gap-1">
                {voice.tags.slice(0, 6).map(tag => (
                  <span key={tag} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{tag}</span>
                ))}
              </p>
            )}

            {selected && versions.length > 0 && (
              <ul className="mt-2 space-y-1.5 border-t border-slate-100 pt-2">
                {versions.map(version => {
                  const isCurrent = version.id === voice.current_version_id
                  return (
                    <li key={version.id} className="rounded-lg bg-slate-50 p-2">
                      <div className="flex items-center justify-between gap-2 text-[11px] text-slate-600">
                        <span className="font-semibold text-slate-800">
                          V{version.version_number}
                          {isCurrent && <span className="ml-1 rounded bg-cyan-100 px-1 py-0.5 text-[9px] font-semibold uppercase text-cyan-700">current</span>}
                          {version.status === 'production-ready' && <span className="ml-1 rounded bg-emerald-100 px-1 py-0.5 text-[9px] font-semibold uppercase text-emerald-700">production-ready</span>}
                        </span>
                        <span className="truncate text-[10px] text-slate-400">{version.change_note || version.created_at || ''}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        <button
                          type="button"
                          disabled={revoked || busy}
                          onClick={() => onUse(selectionFor(voice, version))}
                          className="flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-30"
                        >
                          <Rocket className="h-3 w-3" aria-hidden="true" /> Use for production
                        </button>
                        {optimizationEnabled && (
                          <button
                            type="button"
                            disabled={jobActive || revoked}
                            onClick={() => { void onOptimize(version) }}
                            aria-label={`Optimize a persistent identity from V${version.version_number}`}
                            className="flex items-center gap-1 rounded border border-violet-300 px-2 py-1 text-[10px] font-semibold text-violet-700 disabled:opacity-30"
                          >
                            <Zap className="h-3 w-3" aria-hidden="true" /> Optimize
                          </button>
                        )}
                        {!isCurrent && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => { void onRollback(voice, version) }}
                            aria-label={`Roll back to V${version.version_number}`}
                            className="flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-[10px] font-semibold text-slate-600 disabled:opacity-30"
                          >
                            <History className="h-3 w-3" aria-hidden="true" /> Roll back
                          </button>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </article>
        )
      })}
    </div>
  )
}
