import { useEffect, useMemo, useState } from 'react'
import { Activity, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import type {
  AutomationInterpolation,
  AutomationKeyframe,
  AutomationScopeType,
  AutomationTrack,
  AutomationTrackDraft,
  VoiceCityControl,
} from '../../types/voice-city'

interface AutomationPanelProps {
  voiceId: string | null
  controls: VoiceCityControl[]
  tracks: AutomationTrack[]
  onRefresh: () => void | Promise<void>
  onCreate: (payload: AutomationTrackDraft) => void | Promise<void>
  onUpdate: (trackId: string, patch: Partial<AutomationTrack>) => void | Promise<void>
  onDelete: (trackId: string) => void | Promise<void>
}

const SCOPE_TYPES: AutomationScopeType[] = ['global', 'chapter', 'scene', 'sentence', 'character']
const INTERPOLATIONS: AutomationInterpolation[] = ['linear', 'smooth', 'step']

const SCOPE_HINTS: Record<AutomationScopeType, string> = {
  global: 'One curve across the whole production (scope key "global").',
  chapter: 'Keyed by chapter index, one-based number, or title.',
  scene: 'Keyed by scene index or a chapter:scene composite key.',
  sentence: 'Position runs across sentences inside the scope key.',
  character: 'Keyed by the cast character name.',
}

export function AutomationPanel({ voiceId, controls, tracks, onRefresh, onCreate, onUpdate, onDelete }: AutomationPanelProps) {
  const automatable = useMemo(
    () => controls.filter(control => control.automatable && control.control_type === 'slider'),
    [controls],
  )
  const [parameterPath, setParameterPath] = useState('')
  const [scopeType, setScopeType] = useState<AutomationScopeType>('chapter')
  const [scopeKey, setScopeKey] = useState('global')
  const [interpolation, setInterpolation] = useState<AutomationInterpolation>('linear')
  const [keyframes, setKeyframes] = useState<AutomationKeyframe[]>([{ at: 0, value: 0 }, { at: 1, value: 0.2 }])
  const [editingId, setEditingId] = useState<string | null>(null)

  useEffect(() => {
    void onRefresh()
    // The refresh callback identity changes every render; the voice drives refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceId])

  useEffect(() => {
    if (!parameterPath && automatable.length) setParameterPath(automatable[0].path)
  }, [automatable, parameterPath])

  const controlFor = (path: string): VoiceCityControl | undefined => controls.find(control => control.path === path)
  const activeControl = controlFor(parameterPath)

  const setFrame = (index: number, patch: Partial<AutomationKeyframe>) => {
    setKeyframes(frames => frames.map((frame, position) => (position === index ? { ...frame, ...patch } : frame)))
  }

  const startEdit = (track: AutomationTrack) => {
    setEditingId(track.id)
    setParameterPath(track.parameter_path)
    setScopeType(track.scope_type)
    setScopeKey(track.scope_key)
    setInterpolation(track.interpolation)
    setKeyframes(track.keyframes.map(frame => ({ ...frame })))
  }

  const resetForm = () => {
    setEditingId(null)
    setScopeType('chapter')
    setScopeKey('global')
    setInterpolation('linear')
    setKeyframes([{ at: 0, value: 0 }, { at: 1, value: 0.2 }])
  }

  const submit = () => {
    if (!parameterPath || !scopeKey.trim() || !keyframes.length) return
    const normalized = keyframes
      .map(frame => ({ at: Math.max(0, Math.min(1, frame.at)), value: frame.value }))
      .sort((a, b) => a.at - b.at)
    if (editingId) {
      void onUpdate(editingId, {
        parameter_path: parameterPath,
        scope_type: scopeType,
        scope_key: scopeKey.trim(),
        interpolation,
        keyframes: normalized,
      })
    } else {
      const payload: AutomationTrackDraft = {
        parameter_path: parameterPath,
        scope_type: scopeType,
        scope_key: scopeKey.trim(),
        interpolation,
        keyframes: normalized,
        enabled: true,
      }
      void onCreate(payload)
    }
    resetForm()
  }

  if (!voiceId) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
        <Activity className="mx-auto mb-2 h-5 w-5 text-slate-400" aria-hidden="true" />
        Select a voice in the library to configure performance automation curves.
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(380px,.9fr)_minmax(460px,1.1fr)]">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-violet-600" aria-hidden="true" />
          <h2 className="font-semibold">{editingId ? 'Edit automation track' : 'New automation track'}</h2>
        </div>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Automation moves one numeric performance control across a scope. Positions are normalized 0–1 within the scope; only automation-eligible controls appear here.
        </p>

        <div className="mt-4 space-y-3">
          <label className="block text-xs font-medium text-slate-700">
            Automated control
            <select
              value={parameterPath}
              onChange={event => setParameterPath(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              {!automatable.length && <option value="">No automation-eligible controls in this schema</option>}
              {automatable.map(control => (
                <option key={control.path} value={control.path}>{control.label} ({control.path})</option>
              ))}
            </select>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-slate-700">
              Scope type
              <select
                value={scopeType}
                onChange={event => setScopeType(event.target.value as AutomationScopeType)}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm capitalize"
              >
                {SCOPE_TYPES.map(item => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-700">
              Scope key
              <input
                value={scopeKey}
                onChange={event => setScopeKey(event.target.value)}
                placeholder='e.g. "global", "3", or "Chapter One"'
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <p className="text-[11px] text-slate-400">{SCOPE_HINTS[scopeType]}</p>

          <label className="block text-xs font-medium text-slate-700">
            Interpolation
            <select
              value={interpolation}
              onChange={event => setInterpolation(event.target.value as AutomationInterpolation)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm capitalize"
            >
              {INTERPOLATIONS.map(item => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>

          <fieldset className="rounded-xl border border-slate-200 p-3">
            <legend className="px-1 text-xs font-semibold text-slate-700">Keyframes ({keyframes.length})</legend>
            <div className="space-y-2">
              {keyframes.map((frame, index) => (
                <div key={index} className="flex items-center gap-2">
                  <label className="flex-1 text-[10px] text-slate-500">
                    Position (0–1)
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={frame.at}
                      onChange={event => setFrame(index, { at: Number(event.target.value) })}
                      aria-label={`Keyframe ${index + 1} position`}
                      className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                    />
                  </label>
                  <label className="flex-1 text-[10px] text-slate-500">
                    Value{activeControl?.unit ? ` (${activeControl.unit})` : ''}
                    <input
                      type="number"
                      min={activeControl?.minimum ?? undefined}
                      max={activeControl?.maximum ?? undefined}
                      step={activeControl?.step ?? 0.01}
                      value={frame.value}
                      onChange={event => setFrame(index, { value: Number(event.target.value) })}
                      aria-label={`Keyframe ${index + 1} value`}
                      className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={keyframes.length <= 1}
                    onClick={() => setKeyframes(frames => frames.filter((_, position) => position !== index))}
                    aria-label={`Remove keyframe ${index + 1}`}
                    className="mt-3 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              disabled={keyframes.length >= 500}
              onClick={() => setKeyframes(frames => [...frames, { at: Math.min(1, (frames[frames.length - 1]?.at ?? 0) + 0.25), value: frames[frames.length - 1]?.value ?? 0 }])}
              className="mt-2 flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-30"
            >
              <Plus className="h-3 w-3" aria-hidden="true" /> Add keyframe
            </button>
          </fieldset>

          <div className="flex gap-2">
            <button
              type="button"
              disabled={!parameterPath || !scopeKey.trim() || !keyframes.length}
              onClick={submit}
              className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
            >
              {editingId ? 'Save track' : 'Create track'}
            </button>
            {editingId && (
              <button type="button" onClick={resetForm} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600">
                <X className="h-3.5 w-3.5" aria-hidden="true" /> Cancel
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">Automation tracks ({tracks.length})</h2>
          <button type="button" onClick={() => { void onRefresh() }} aria-label="Refresh automation tracks" className="flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
            <RefreshCw className="h-3 w-3" aria-hidden="true" /> Refresh
          </button>
        </div>
        {!tracks.length ? (
          <p className="mt-4 rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
            No automation yet. Add a track to move energy, pace, or intimacy across chapters and scenes.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {tracks.map(track => {
              const control = controlFor(track.parameter_path)
              return (
                <li key={track.id} className={`rounded-xl border p-3 ${track.enabled ? 'border-slate-200' : 'border-slate-100 bg-slate-50 opacity-70'}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">{control?.label || track.parameter_path}</p>
                      <p className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-slate-500">
                        <span className="rounded bg-violet-50 px-1.5 py-0.5 capitalize text-violet-700">{track.scope_type}: {track.scope_key}</span>
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 capitalize">{track.interpolation}</span>
                        <span className="rounded bg-slate-100 px-1.5 py-0.5">{track.keyframes.length} keyframe{track.keyframes.length === 1 ? '' : 's'}</span>
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <label className="flex items-center gap-1 text-[10px] text-slate-500">
                        <input
                          type="checkbox"
                          checked={track.enabled}
                          onChange={event => { void onUpdate(track.id, { enabled: event.target.checked }) }}
                          aria-label={`Toggle automation of ${control?.label || track.parameter_path}`}
                          className="h-3.5 w-3.5 accent-violet-600"
                        />
                        On
                      </label>
                      <button type="button" onClick={() => startEdit(track)} aria-label={`Edit automation of ${control?.label || track.parameter_path}`} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" onClick={() => { void onDelete(track.id) }} aria-label={`Delete automation of ${control?.label || track.parameter_path}`} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                  <p className="mt-1.5 truncate text-[10px] text-slate-400">
                    {track.keyframes.map(frame => `${Math.round(frame.at * 100)}% → ${frame.value}`).join('  ·  ')}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}
