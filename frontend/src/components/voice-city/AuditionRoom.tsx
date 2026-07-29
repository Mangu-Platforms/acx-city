import { useEffect, useMemo, useState } from 'react'
import { Headphones, Loader2, Play, X } from 'lucide-react'
import type { AuditionScript, VoicePreview } from '../../types/voice-city'

interface AuditionPreviewOptions {
  scriptId?: string
  text?: string
  loudnessMatch: boolean
}

interface AuditionRoomProps {
  scripts: AuditionScript[]
  preview: VoicePreview | null
  busy: boolean
  sourceLabel: string
  onPreview: (options: AuditionPreviewOptions) => void
  onClear: () => void
}

const scriptLabel = (script: AuditionScript): string => script.title || script.name || script.id

function formatDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '—'
  return `${seconds.toFixed(1)}s`
}

export function AuditionRoom({ scripts, preview, busy, sourceLabel, onPreview, onClear }: AuditionRoomProps) {
  const [category, setCategory] = useState('all')
  const [scriptId, setScriptId] = useState('')
  const [useCustomText, setUseCustomText] = useState(false)
  const [customText, setCustomText] = useState('')
  const [loudnessMatch, setLoudnessMatch] = useState(true)

  const categories = useMemo(
    () => [...new Set(scripts.map(script => script.category))].sort((a, b) => a.localeCompare(b)),
    [scripts],
  )
  const visibleScripts = useMemo(
    () => scripts.filter(script => category === 'all' || script.category === category),
    [scripts, category],
  )
  const activeScript = scripts.find(script => script.id === scriptId) || null

  useEffect(() => {
    if (visibleScripts.length && !visibleScripts.some(script => script.id === scriptId)) {
      setScriptId(visibleScripts[0].id)
    }
  }, [visibleScripts, scriptId])

  const canRender = Boolean(sourceLabel) && !busy && (useCustomText ? Boolean(customText.trim()) : Boolean(scriptId))

  const render = () => {
    if (useCustomText) onPreview({ text: customText.trim(), loudnessMatch })
    else onPreview({ scriptId: scriptId || undefined, loudnessMatch })
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Headphones className="h-4 w-4 text-cyan-600" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-slate-900">Audition room</h2>
        </div>
        {sourceLabel
          ? <span className="rounded-full bg-cyan-50 px-2.5 py-1 text-[11px] font-medium text-cyan-800">Auditioning {sourceLabel}</span>
          : <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-500">Pick a candidate or library voice first</span>}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(120px,auto)_1fr]">
        <label className="text-xs font-medium text-slate-700">
          Script category
          <select
            value={category}
            onChange={event => setCategory(event.target.value)}
            disabled={useCustomText}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs capitalize disabled:opacity-50"
          >
            <option value="all">All categories</option>
            {categories.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-700">
          Audition script
          <select
            value={scriptId}
            onChange={event => setScriptId(event.target.value)}
            disabled={useCustomText || !visibleScripts.length}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs disabled:opacity-50"
          >
            {!visibleScripts.length && <option value="">No scripts available</option>}
            {visibleScripts.map(script => (
              <option key={script.id} value={script.id}>{scriptLabel(script)}</option>
            ))}
          </select>
        </label>
      </div>

      {!useCustomText && activeScript && (
        <blockquote className="mt-2 max-h-20 overflow-y-auto rounded-lg bg-slate-50 p-2.5 text-xs leading-5 text-slate-600">
          {activeScript.text}
        </blockquote>
      )}

      <label className="mt-3 flex items-center gap-2 text-xs text-slate-600">
        <input
          type="checkbox"
          checked={useCustomText}
          onChange={event => setUseCustomText(event.target.checked)}
          className="h-3.5 w-3.5 accent-cyan-600"
        />
        Audition custom text instead
      </label>
      {useCustomText && (
        <label className="mt-2 block text-xs font-medium text-slate-700">
          <span className="sr-only">Custom audition text</span>
          <textarea
            value={customText}
            onChange={event => setCustomText(event.target.value)}
            placeholder="Paste a paragraph to audition with this voice…"
            className="h-24 w-full rounded-lg border border-slate-300 p-2.5 text-xs"
          />
        </label>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-xs text-slate-600" title="Match perceived loudness across renders so comparisons stay fair.">
          <input
            type="checkbox"
            checked={loudnessMatch}
            onChange={event => setLoudnessMatch(event.target.checked)}
            className="h-3.5 w-3.5 accent-cyan-600"
          />
          Loudness-matched playback
        </label>
        <button
          type="button"
          disabled={!canRender}
          onClick={render}
          className="flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Play className="h-3.5 w-3.5" aria-hidden="true" />}
          {busy ? 'Rendering…' : 'Render preview'}
        </button>
      </div>

      {preview && (
        <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50/70 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="min-w-0 truncate text-xs font-semibold text-cyan-950">
              {preview.display_name || 'Preview'}
              <span className="ml-2 font-normal text-cyan-700">{formatDuration(preview.duration_s)} · {preview.status}{preview.cache_hit ? ' · cached' : ''}</span>
            </p>
            <button type="button" onClick={onClear} aria-label="Clear preview" className="rounded p-1 text-cyan-700 hover:bg-cyan-100">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {preview.url ? (
            <audio controls src={preview.url} className="mt-2 w-full" aria-label={`Audio preview for ${preview.display_name || 'the selected voice'}`} />
          ) : (
            <p className="mt-2 text-[11px] text-cyan-800">{preview.error || 'The signed audio URL is not available for this preview.'}</p>
          )}
        </div>
      )}
    </section>
  )
}
