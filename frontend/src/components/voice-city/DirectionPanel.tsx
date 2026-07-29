import React, { useEffect, useMemo, useState } from 'react'
import { BookOpen, Plus, ScanText, Trash2, Users } from 'lucide-react'
import type {
  VoiceCityVersion,
  VoiceCityVoice,
  VoiceDirectionAnalysis,
  VoiceDirectionCastEntry,
  VoiceDirectionPlan,
  VoiceParameters,
} from '../../types/voice-city'

interface DirectionPanelProps {
  manuscriptText: string
  voices: VoiceCityVoice[]
  plan: VoiceDirectionPlan
  analysis: VoiceDirectionAnalysis | null
  busy: boolean
  onAnalyze: (text: string) => Promise<void>
  onChange: (plan: VoiceDirectionPlan) => void
}

interface VersionOption {
  id: string
  label: string
  voice: VoiceCityVoice
  version: VoiceCityVersion
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function getNumber(document: VoiceParameters | undefined, group: string, key: string, fallback: number): number {
  const value = document?.[group]?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function setNumber(document: VoiceParameters | undefined, group: string, key: string, value: number): VoiceParameters {
  const next = clone(document || {})
  next[group] = { ...(next[group] || {}), [key]: value }
  return next
}

function mergeSpeakerCast(plan: VoiceDirectionPlan, speaker: string, versionId: string): VoiceDirectionPlan {
  const existing = plan.cast.find(item => item.character_name === speaker)
  const remaining = plan.cast.filter(item => item.character_name !== speaker)
  if (!versionId) return { ...plan, cast: remaining }
  const entry: VoiceDirectionCastEntry = {
    character_name: speaker,
    aliases: existing?.aliases || [],
    voice_version_id: versionId,
    style_overrides: existing?.style_overrides || {},
  }
  return { ...plan, cast: [...remaining, entry] }
}

export function DirectionPanel({ manuscriptText, voices, plan, analysis, busy, onAnalyze, onChange }: DirectionPanelProps) {
  const [analysisText, setAnalysisText] = useState(manuscriptText)
  const [manualCharacter, setManualCharacter] = useState('')
  const [manualSpeakers, setManualSpeakers] = useState<string[]>([])
  const [chapterStylesText, setChapterStylesText] = useState(JSON.stringify(plan.chapter_styles || {}, null, 2))
  const [sceneStylesText, setSceneStylesText] = useState(JSON.stringify(plan.scene_styles || {}, null, 2))
  const [advancedError, setAdvancedError] = useState<string | null>(null)

  useEffect(() => {
    if (manuscriptText && !analysisText.trim()) setAnalysisText(manuscriptText)
  }, [manuscriptText, analysisText])

  useEffect(() => setChapterStylesText(JSON.stringify(plan.chapter_styles || {}, null, 2)), [plan.chapter_styles])
  useEffect(() => setSceneStylesText(JSON.stringify(plan.scene_styles || {}, null, 2)), [plan.scene_styles])

  const versionOptions = useMemo<VersionOption[]>(() => {
    const options: VersionOption[] = []
    const seen = new Set<string>()
    for (const voice of voices) {
      const versions = voice.versions?.length ? voice.versions : voice.current_version ? [voice.current_version] : []
      for (const version of versions) {
        if (seen.has(version.id)) continue
        seen.add(version.id)
        options.push({ id: version.id, label: `${voice.name} V${version.version_number} · ${version.provider}`, voice, version })
      }
    }
    return options.sort((a, b) => a.label.localeCompare(b.label))
  }, [voices])

  const speakers = useMemo(() => {
    const names = new Set<string>((analysis?.speakers || []).map(item => item.name))
    plan.cast.forEach(item => names.add(item.character_name))
    manualSpeakers.forEach(item => names.add(item))
    return [...names]
  }, [analysis, plan.cast, manualSpeakers])

  const addManualCharacter = () => {
    const name = manualCharacter.trim()
    if (!name || speakers.some(item => item.toLocaleLowerCase() === name.toLocaleLowerCase())) return
    setManualSpeakers(items => [...items, name])
    setManualCharacter('')
  }

  const updateCast = (characterName: string, patch: Partial<VoiceDirectionCastEntry>) => {
    const current = plan.cast.find(item => item.character_name === characterName) || {
      character_name: characterName,
      aliases: [],
      voice_version_id: '',
      style_overrides: {},
    }
    const next = { ...current, ...patch }
    const remaining = plan.cast.filter(item => item.character_name !== characterName)
    onChange({ ...plan, cast: [...remaining, next] })
  }

  const applyAdvancedStyles = () => {
    try {
      const chapterStyles = JSON.parse(chapterStylesText || '{}')
      const sceneStyles = JSON.parse(sceneStylesText || '{}')
      if (!chapterStyles || Array.isArray(chapterStyles) || typeof chapterStyles !== 'object') throw new Error('Chapter styles must be a JSON object.')
      if (!sceneStyles || Array.isArray(sceneStyles) || typeof sceneStyles !== 'object') throw new Error('Scene styles must be a JSON object.')
      onChange({ ...plan, chapter_styles: chapterStyles, scene_styles: sceneStyles })
      setAdvancedError(null)
    } catch (error) {
      setAdvancedError(error instanceof Error ? error.message : 'Invalid style JSON')
    }
  }

  const dialogueOverrides = plan.default_dialogue_overrides || {}
  const analysisSpeaker = (name: string) => analysis?.speakers.find(item => item.name === name)

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(340px,.8fr)_minmax(520px,1.2fr)]">
      <div className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2"><ScanText className="h-5 w-5 text-cyan-600" /><h2 className="font-semibold">Analyze manuscript dialogue</h2></div>
          <p className="mt-2 text-sm leading-6 text-slate-600">The deterministic detector casts only evidence-backed speaker attributions. Uncertain quoted dialogue stays with the narrator unless you explicitly choose to skip it.</p>
          <textarea value={analysisText} onChange={event => setAnalysisText(event.target.value)} placeholder="Paste a scene or use the manuscript already loaded in production." className="mt-4 h-44 w-full rounded-xl border border-slate-300 p-3 text-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-100" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>{analysisText.length.toLocaleString()} characters</span><button type="button" disabled={busy || !analysisText.trim()} onClick={() => onAnalyze(analysisText)} className="rounded-lg bg-cyan-600 px-3 py-2 font-semibold text-white disabled:opacity-40">Analyze speakers</button></div>
          {analysis && <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">{[
            ['Scenes', analysis.scene_count], ['Speakers', analysis.speakers.length], ['Dialogue', analysis.dialogue_segment_count], ['Unattributed', analysis.unattributed_dialogue_count],
          ].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-slate-50 p-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p><strong className="text-lg text-slate-900">{value}</strong></div>)}</div>}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2"><BookOpen className="h-5 w-5 text-violet-600" /><h2 className="font-semibold">Director instructions</h2></div>
          <textarea value={plan.director_instructions} onChange={event => onChange({ ...plan, director_instructions: event.target.value })} placeholder="Example: Keep the narrator restrained and intimate; let dialogue become more conversational; tighten suspense in scene transitions." className="mt-3 h-28 w-full rounded-xl border border-slate-300 p-3 text-sm" />
          <div className="mt-4 space-y-3 text-sm">
            <label className="flex items-center justify-between gap-4"><span><strong className="block text-slate-800">Enable direction plan</strong><span className="text-xs text-slate-500">Store the entire plan in the immutable production snapshot.</span></span><input type="checkbox" checked={plan.enabled} onChange={event => onChange({ ...plan, enabled: event.target.checked })} className="h-4 w-4 accent-cyan-600" /></label>
            <label className="flex items-center justify-between gap-4"><span><strong className="block text-slate-800">Automatic dialogue detection</strong><span className="text-xs text-slate-500">Detect quote turns and screenplay-style CHARACTER: lines.</span></span><input type="checkbox" checked={plan.automatic_dialogue_detection} onChange={event => onChange({ ...plan, automatic_dialogue_detection: event.target.checked })} className="h-4 w-4 accent-cyan-600" /></label>
            <label className="block"><span className="mb-1 block font-medium text-slate-700">Unattributed dialogue policy</span><select value={plan.unknown_dialogue_policy} onChange={event => onChange({ ...plan, unknown_dialogue_policy: event.target.value as 'narrator' | 'skip' })} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option value="narrator">Narrator reads it</option><option value="skip">Skip the unattributed dialogue</option></select></label>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Default dialogue performance</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">These changes affect dialogue performance only. Speaker identity controls remain immutable.</p>
          {[
            ['Dialogue lift', 'narration', 'dialogue_lift', -1, 1, getNumber(dialogueOverrides, 'narration', 'dialogue_lift', 0.2)],
            ['Energy', 'performance', 'energy', 0, 1, getNumber(dialogueOverrides, 'performance', 'energy', 0.55)],
            ['Conversationality', 'performance', 'conversationality', 0, 1, getNumber(dialogueOverrides, 'performance', 'conversationality', 0.7)],
            ['Emotional intensity', 'performance', 'emotional_intensity', 0, 1, getNumber(dialogueOverrides, 'performance', 'emotional_intensity', 0.5)],
          ].map(([label, group, key, min, max, value]) => <label key={String(key)} className="mt-4 block"><span className="flex items-center justify-between text-xs font-medium text-slate-700"><span>{label}</span><span>{Number(value).toFixed(2)}</span></span><input type="range" min={Number(min)} max={Number(max)} step={0.01} value={Number(value)} onChange={event => onChange({ ...plan, default_dialogue_overrides: setNumber(dialogueOverrides, String(group), String(key), Number(event.target.value)) })} className="mt-2 w-full accent-violet-600" /></label>)}
        </section>
      </div>

      <div className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><Users className="h-5 w-5 text-fuchsia-600" /><div><h2 className="font-semibold">Character casting</h2><p className="text-xs text-slate-500">Each selected version is copied into the job snapshot with its own provider, model revision, rules, automation, and fingerprint.</p></div></div><div className="flex gap-2"><input value={manualCharacter} onChange={event => setManualCharacter(event.target.value)} onKeyDown={(event: any) => { if (event.key === 'Enter') { event.preventDefault(); addManualCharacter() } }} placeholder="Add character" className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-xs" /><button type="button" onClick={addManualCharacter} className="rounded-lg border border-slate-300 p-2 text-slate-700"><Plus className="h-4 w-4" /></button></div></div>
          {!speakers.length ? <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Analyze manuscript text or add a character manually to begin casting.</div> : <div className="mt-4 space-y-3">{speakers.map(name => {
            const cast = plan.cast.find(item => item.character_name === name)
            const detected = analysisSpeaker(name)
            return <div key={name} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><strong className="text-sm text-slate-900">{name}</strong>{detected && <p className="mt-0.5 text-xs text-slate-500">{detected.turns} detected turn{detected.turns === 1 ? '' : 's'}</p>}</div><button type="button" onClick={() => { onChange({ ...plan, cast: plan.cast.filter(item => item.character_name !== name) }); setManualSpeakers(items => items.filter(item => item !== name)) }} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Clear ${name} casting`}><Trash2 className="h-4 w-4" /></button></div><select value={cast?.voice_version_id || ''} onChange={event => onChange(mergeSpeakerCast(plan, name, event.target.value))} className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="">Narrator fallback / uncast</option>{versionOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select>{cast?.voice_version_id && <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs text-slate-600">Aliases<input value={(cast.aliases || []).join(', ')} onChange={event => updateCast(name, { aliases: event.target.value.split(',').map(item => item.trim()).filter(Boolean) })} placeholder="Dr. Smith, Doctor" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></label><label className="text-xs text-slate-600">Character energy <span className="float-right">{getNumber(cast.style_overrides, 'performance', 'energy', 0.5).toFixed(2)}</span><input type="range" min={0} max={1} step={0.01} value={getNumber(cast.style_overrides, 'performance', 'energy', 0.5)} onChange={event => updateCast(name, { style_overrides: setNumber(cast.style_overrides, 'performance', 'energy', Number(event.target.value)) })} className="mt-2 w-full accent-fuchsia-600" /></label></div>}{detected?.excerpts?.length ? <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer font-medium text-slate-700">Detected excerpts</summary><div className="mt-2 space-y-2">{detected.excerpts.map((excerpt, index) => <blockquote key={index} className="border-l-2 border-slate-200 pl-3">{excerpt}</blockquote>)}</div></details> : null}</div>
          })}</div>}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Chapter and scene styles</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">Keys may be chapter indices, one-based chapter numbers, chapter titles, scene indices, or composite keys such as <code>2:1</code>. Values may be natural-language direction strings or sparse parameter patches.</p>
          <div className="mt-4 grid gap-4 lg:grid-cols-2"><label className="text-xs font-medium text-slate-700">Chapter styles JSON<textarea value={chapterStylesText} onChange={event => setChapterStylesText(event.target.value)} className="mt-2 h-44 w-full rounded-xl border border-slate-300 p-3 font-mono text-xs" /></label><label className="text-xs font-medium text-slate-700">Scene styles JSON<textarea value={sceneStylesText} onChange={event => setSceneStylesText(event.target.value)} className="mt-2 h-44 w-full rounded-xl border border-slate-300 p-3 font-mono text-xs" /></label></div>
          {advancedError && <p className="mt-2 text-xs text-red-600">{advancedError}</p>}
          <button type="button" onClick={applyAdvancedStyles} className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white">Validate and apply styles</button>
        </section>

        {analysis && <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-950"><strong>{analysis.detector}</strong><p className="mt-1 text-xs leading-5 text-cyan-800">{analysis.policy}</p><div className="mt-3 max-h-48 overflow-y-auto rounded-lg bg-white/80 p-3">{analysis.segments.filter(segment => segment.kind === 'dialogue').slice(0, 40).map(segment => <div key={segment.index} className="mb-2 grid grid-cols-[110px_1fr] gap-2 text-xs"><span className="font-semibold text-slate-700">{segment.speaker || 'Narrator fallback'}</span><span className="text-slate-600">{segment.text.trim()}</span></div>)}</div></section>}
      </div>
    </div>
  )
}
