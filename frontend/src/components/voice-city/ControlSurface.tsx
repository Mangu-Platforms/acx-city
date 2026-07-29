import { useMemo, useState } from 'react'
import { Lock, RotateCcw, Search, SlidersHorizontal, Unlock, Zap } from 'lucide-react'
import type { VoiceCityControl, VoiceCitySchema, VoiceParameters } from '../../types/voice-city'
import { getPath, setPath } from './utils'

interface ControlSurfaceProps {
  schema: VoiceCitySchema | null
  parameters: VoiceParameters
  lockedPaths: Set<string>
  onChange: (next: VoiceParameters) => void
  onToggleLock: (path: string) => void
  onResetControl: (control: VoiceCityControl) => void
}

function matchesSearch(control: VoiceCityControl, needle: string): boolean {
  if (!needle) return true
  const haystack = [control.label, control.path, control.description, control.audible_impact, ...control.aliases, ...control.tags]
    .join(' ')
    .toLowerCase()
  return needle
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every(term => haystack.includes(term))
}

function numberValue(parameters: VoiceParameters, control: VoiceCityControl): number {
  const raw = getPath(parameters, control.path)
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  return typeof control.default === 'number' ? control.default : 0
}

function stringValue(parameters: VoiceParameters, control: VoiceCityControl): string {
  const raw = getPath(parameters, control.path)
  if (typeof raw === 'string') return raw
  return typeof control.default === 'string' ? control.default : (control.options[0] || '')
}

function booleanValue(parameters: VoiceParameters, control: VoiceCityControl): boolean {
  const raw = getPath(parameters, control.path)
  if (typeof raw === 'boolean') return raw
  return control.default === true
}

export function ControlSurface({ schema, parameters, lockedPaths, onChange, onToggleLock, onResetControl }: ControlSurfaceProps) {
  const [search, setSearch] = useState('')

  const groupedControls = useMemo(() => {
    if (!schema) return []
    const needle = search.trim()
    const byGroup = new Map<string, VoiceCityControl[]>()
    for (const control of schema.controls) {
      if (!matchesSearch(control, needle)) continue
      const bucket = byGroup.get(control.group)
      if (bucket) bucket.push(control)
      else byGroup.set(control.group, [control])
    }
    return [...schema.groups]
      .sort((a, b) => a.order - b.order)
      .map(group => ({ group, controls: byGroup.get(group.id) || [] }))
      .filter(entry => entry.controls.length > 0)
  }, [schema, search])

  const visibleCount = groupedControls.reduce((total, entry) => total + entry.controls.length, 0)

  if (!schema) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 text-slate-500">
          <SlidersHorizontal className="h-4 w-4" />
          <p className="text-sm">Loading the parameter contract…</p>
        </div>
      </section>
    )
  }

  const commit = (control: VoiceCityControl, value: string | number | boolean) => {
    onChange(setPath(parameters, control.path, value))
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-cyan-600" />
          <h2 className="text-sm font-semibold text-slate-900">Control surface</h2>
        </div>
        <span className="text-[11px] text-slate-500">
          {visibleCount} of {schema.controls.length} controls · schema {schema.schema_version}
        </span>
      </div>

      <label className="mt-3 flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="sr-only">Search controls</span>
        <input
          value={search}
          onChange={event => setSearch(event.target.value)}
          placeholder="Search controls, paths, aliases…"
          className="min-w-0 flex-1 border-0 bg-transparent text-sm focus:outline-none"
        />
        {search && (
          <button type="button" onClick={() => setSearch('')} className="text-xs text-slate-400 hover:text-slate-600" aria-label="Clear control search">
            ×
          </button>
        )}
      </label>

      {!groupedControls.length && (
        <p className="mt-4 rounded-lg border border-dashed border-slate-300 p-4 text-center text-xs text-slate-500">
          No controls match this search in the current mode.
        </p>
      )}

      <div className="mt-4 space-y-5">
        {groupedControls.map(({ group, controls }) => (
          <div key={group.id}>
            <div className="border-b border-slate-100 pb-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700">{group.title}</h3>
              <p className="text-[11px] text-slate-400">{group.description}</p>
            </div>
            <div className="mt-2 space-y-3">
              {controls.map(control => {
                const locked = lockedPaths.has(control.path)
                return (
                  <div key={control.path} className={`rounded-lg border p-3 ${locked ? 'border-amber-300 bg-amber-50/60' : 'border-slate-100 bg-slate-50/60'}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-slate-800" title={`${control.path} — ${control.description}`}>
                          {control.label}
                          {control.unit ? <span className="ml-1 text-[10px] text-slate-400">({control.unit})</span> : null}
                        </p>
                        <p className="truncate text-[10px] text-slate-400" title={control.audible_impact}>{control.audible_impact}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        {control.automatable && (
                          <span title="Automation-eligible control" className="rounded bg-violet-100 p-1 text-violet-600">
                            <Zap className="h-3 w-3" aria-hidden="true" />
                            <span className="sr-only">Automation-eligible</span>
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => onToggleLock(control.path)}
                          aria-pressed={locked}
                          aria-label={locked ? `Unlock ${control.label}` : `Lock ${control.label} during generation`}
                          className={`rounded p-1 ${locked ? 'bg-amber-200 text-amber-800' : 'text-slate-400 hover:bg-slate-200 hover:text-slate-700'}`}
                        >
                          {locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
                        </button>
                        <button
                          type="button"
                          onClick={() => onResetControl(control)}
                          aria-label={`Reset ${control.label} to its default`}
                          className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>

                    {control.control_type === 'slider' && (
                      <div className="mt-2 flex items-center gap-2">
                        <input
                          type="range"
                          min={control.minimum ?? -1}
                          max={control.maximum ?? 1}
                          step={control.step ?? 0.01}
                          value={numberValue(parameters, control)}
                          onChange={event => commit(control, Number(event.target.value))}
                          aria-label={control.label}
                          className="min-w-0 flex-1 accent-cyan-600"
                        />
                        <input
                          type="number"
                          min={control.minimum ?? undefined}
                          max={control.maximum ?? undefined}
                          step={control.step ?? 0.01}
                          value={numberValue(parameters, control)}
                          onChange={event => {
                            const next = Number(event.target.value)
                            if (Number.isFinite(next)) commit(control, next)
                          }}
                          aria-label={`${control.label} exact value`}
                          className="w-20 rounded border border-slate-300 bg-white px-1.5 py-1 text-right text-xs"
                        />
                      </div>
                    )}

                    {control.control_type === 'select' && (
                      <select
                        value={stringValue(parameters, control)}
                        onChange={event => commit(control, event.target.value)}
                        aria-label={control.label}
                        className="mt-2 w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-xs"
                      >
                        {control.options.map(option => (
                          <option key={option} value={option}>{option}</option>
                        ))}
                      </select>
                    )}

                    {control.control_type === 'toggle' && (
                      <label className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-600">
                        <span>Enabled</span>
                        <input
                          type="checkbox"
                          checked={booleanValue(parameters, control)}
                          onChange={event => commit(control, event.target.checked)}
                          aria-label={control.label}
                          className="h-4 w-4 accent-cyan-600"
                        />
                      </label>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
