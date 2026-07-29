import { useEffect, useMemo, useState } from 'react'
import { BookA, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import type { PronunciationRule, PronunciationRuleKind } from '../../types/voice-city'

interface PronunciationPanelProps {
  voiceId: string | null
  rules: PronunciationRule[]
  onRefresh: () => void | Promise<void>
  onCreate: (rule: PronunciationRule & { voice_id?: string | null }) => void | Promise<void>
  onUpdate: (ruleId: string, patch: Partial<PronunciationRule>) => void | Promise<void>
  onDelete: (ruleId: string) => void | Promise<void>
}

interface RuleDraft {
  pattern: string
  replacement: string
  rule_type: PronunciationRuleKind
  language: string
  priority: number
  case_sensitive: boolean
  enabled: boolean
  notes: string
}

const EMPTY_DRAFT: RuleDraft = {
  pattern: '',
  replacement: '',
  rule_type: 'literal',
  language: 'en-US',
  priority: 100,
  case_sensitive: false,
  enabled: true,
  notes: '',
}

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Local approximation of the server-side rule engine for quick listening checks. */
function applyRulesLocally(text: string, rules: PronunciationRule[]): string {
  let result = text
  const active = [...rules].filter(rule => rule.enabled).sort((a, b) => b.priority - a.priority)
  for (const rule of active) {
    try {
      const source = rule.rule_type === 'pattern' ? rule.pattern : escapeRegExp(rule.pattern)
      result = result.replace(new RegExp(source, rule.case_sensitive ? 'g' : 'gi'), rule.replacement)
    } catch {
      // Invalid pattern; the server will reject it — skip locally.
    }
  }
  return result
}

export function PronunciationPanel({ voiceId, rules, onRefresh, onCreate, onUpdate, onDelete }: PronunciationPanelProps) {
  const [draft, setDraft] = useState<RuleDraft>(EMPTY_DRAFT)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [scopeToVoice, setScopeToVoice] = useState(true)
  const [sampleText, setSampleText] = useState('Dr. Nguyen read the CSV data aloud at 10 a.m.')

  useEffect(() => {
    void onRefresh()
    // The refresh callback identity changes every render; scope changes drive refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceId])

  const preview = useMemo(() => applyRulesLocally(sampleText, rules), [sampleText, rules])
  const patch = (partial: Partial<RuleDraft>) => setDraft(current => ({ ...current, ...partial }))

  const startEdit = (rule: PronunciationRule) => {
    if (!rule.id) return
    setEditingId(rule.id)
    setDraft({
      pattern: rule.pattern,
      replacement: rule.replacement,
      rule_type: rule.rule_type,
      language: rule.language,
      priority: rule.priority,
      case_sensitive: rule.case_sensitive,
      enabled: rule.enabled,
      notes: rule.notes || '',
    })
  }

  const resetForm = () => {
    setEditingId(null)
    setDraft(EMPTY_DRAFT)
  }

  const submit = () => {
    if (!draft.pattern.trim() || !draft.replacement.trim()) return
    const payload: PronunciationRule = {
      pattern: draft.pattern.trim(),
      replacement: draft.replacement.trim(),
      rule_type: draft.rule_type,
      language: draft.language.trim() || 'en-US',
      priority: Number.isFinite(draft.priority) ? draft.priority : 100,
      case_sensitive: draft.case_sensitive,
      enabled: draft.enabled,
      notes: draft.notes.trim() || null,
    }
    if (editingId) void onUpdate(editingId, payload)
    else void onCreate({ ...payload, voice_id: scopeToVoice && voiceId ? voiceId : null })
    resetForm()
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(360px,.9fr)_minmax(460px,1.1fr)]">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <BookA className="h-5 w-5 text-cyan-600" aria-hidden="true" />
          <h2 className="font-semibold">{editingId ? 'Edit pronunciation rule' : 'New pronunciation rule'}</h2>
        </div>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Rules rewrite text before synthesis. Literal rules match exact spellings; pattern rules use regular expressions. Higher priority wins.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-700">
            Grapheme / pattern
            <input
              value={draft.pattern}
              onChange={event => patch({ pattern: event.target.value })}
              placeholder="e.g. Nguyen"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Spoken replacement
            <input
              value={draft.replacement}
              onChange={event => patch({ replacement: event.target.value })}
              placeholder="e.g. win"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Kind
            <select
              value={draft.rule_type}
              onChange={event => patch({ rule_type: event.target.value as PronunciationRuleKind })}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="literal">Literal text</option>
              <option value="pattern">Pattern (regular expression)</option>
            </select>
          </label>
          <label className="text-xs font-medium text-slate-700">
            Language
            <input
              value={draft.language}
              onChange={event => patch({ language: event.target.value })}
              placeholder="en-US"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Priority
            <input
              type="number"
              value={draft.priority}
              onChange={event => patch({ priority: Number(event.target.value) })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Notes
            <input
              value={draft.notes}
              onChange={event => patch({ notes: event.target.value })}
              placeholder="Why this rule exists (optional)"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="mt-3 space-y-2 text-xs text-slate-600">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={draft.case_sensitive} onChange={event => patch({ case_sensitive: event.target.checked })} className="h-3.5 w-3.5 accent-cyan-600" />
            Case-sensitive matching
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={draft.enabled} onChange={event => patch({ enabled: event.target.checked })} className="h-3.5 w-3.5 accent-cyan-600" />
            Enabled
          </label>
          {!editingId && (
            <label className={`flex items-center gap-2 ${voiceId ? '' : 'opacity-50'}`}>
              <input type="checkbox" checked={scopeToVoice && Boolean(voiceId)} disabled={!voiceId} onChange={event => setScopeToVoice(event.target.checked)} className="h-3.5 w-3.5 accent-cyan-600" />
              Limit to the selected voice {voiceId ? '' : '(select a voice to enable)'}
            </label>
          )}
        </div>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            disabled={!draft.pattern.trim() || !draft.replacement.trim()}
            onClick={submit}
            className="flex items-center gap-1.5 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" /> {editingId ? 'Save changes' : 'Add rule'}
          </button>
          {editingId && (
            <button type="button" onClick={resetForm} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600">
              <X className="h-3.5 w-3.5" aria-hidden="true" /> Cancel
            </button>
          )}
        </div>

        <div className="mt-5 border-t border-slate-100 pt-4">
          <h3 className="text-xs font-semibold text-slate-700">Test rules on sample text</h3>
          <label className="mt-2 block text-xs text-slate-600">
            <span className="sr-only">Sample text</span>
            <textarea value={sampleText} onChange={event => setSampleText(event.target.value)} className="h-16 w-full rounded-lg border border-slate-300 p-2.5 text-xs" />
          </label>
          <p className="mt-2 rounded-lg bg-slate-50 p-2.5 text-xs leading-5 text-slate-700"><span className="mr-1 font-semibold text-slate-500">Reads as:</span>{preview}</p>
          <p className="mt-1 text-[10px] text-slate-400">Local approximation — the server applies the authoritative engine at render time.</p>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">Dictionary ({rules.length})</h2>
          <button type="button" onClick={() => { void onRefresh() }} aria-label="Refresh pronunciation rules" className="flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
            <RefreshCw className="h-3 w-3" aria-hidden="true" /> Refresh
          </button>
        </div>
        {!rules.length ? (
          <p className="mt-4 rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
            No rules yet. Library-wide rules apply to every voice; voice rules apply only when that voice narrates.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {rules.map(rule => (
              <li key={rule.id || `${rule.pattern}-${rule.replacement}`} className={`rounded-xl border p-3 ${rule.enabled ? 'border-slate-200' : 'border-slate-100 bg-slate-50 opacity-70'}`}>
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 text-sm text-slate-900">
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{rule.pattern}</code>
                    <span className="mx-1.5 text-slate-400">→</span>
                    <code className="rounded bg-cyan-50 px-1.5 py-0.5 text-xs text-cyan-800">{rule.replacement}</code>
                  </p>
                  <div className="flex shrink-0 items-center gap-1">
                    <label className="flex items-center gap-1 text-[10px] text-slate-500">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        onChange={event => { if (rule.id) void onUpdate(rule.id, { enabled: event.target.checked }) }}
                        aria-label={`Toggle rule ${rule.pattern}`}
                        className="h-3.5 w-3.5 accent-cyan-600"
                      />
                      On
                    </label>
                    <button type="button" onClick={() => startEdit(rule)} aria-label={`Edit rule ${rule.pattern}`} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => { if (rule.id) void onDelete(rule.id) }} aria-label={`Delete rule ${rule.pattern}`} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <p className="mt-1.5 flex flex-wrap gap-1 text-[10px] text-slate-500">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 capitalize">{rule.rule_type}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5">{rule.language}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5">priority {rule.priority}</span>
                  {rule.case_sensitive && <span className="rounded bg-slate-100 px-1.5 py-0.5">case-sensitive</span>}
                  <span className={`rounded px-1.5 py-0.5 ${rule.voice_id ? 'bg-cyan-50 text-cyan-700' : 'bg-violet-50 text-violet-700'}`}>{rule.voice_id ? 'voice-specific' : 'library-wide'}</span>
                </p>
                {rule.notes && <p className="mt-1 text-[11px] text-slate-400">{rule.notes}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
