import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Beaker, BookOpen, Check, ChevronLeft, Dna, FlaskConical, GitMerge,
  Library, LockKeyhole, Save, ShieldCheck, SlidersHorizontal, Sparkles,
  Undo2, Redo2, Volume2, WandSparkles,
} from 'lucide-react'
import { voiceCityAPI } from '../../services/voiceCityApi'
import type {
  AuditionScript, AutomationTrack, PronunciationRule, QualityMetrics,
  VoiceCityCandidate, VoiceCityCapabilities, VoiceCityGenerationJob, VoiceCityMode,
  VoiceCityPreset, VoiceCitySchema, VoiceCitySelection, VoiceCityVoice,
  VoiceDirectionAnalysis, VoiceDirectionPlan,
  VoiceCityVersion, VoiceParameters, VoicePreview,
} from '../../types/voice-city'
import { AuditionRoom } from './AuditionRoom'
import { AutomationPanel } from './AutomationPanel'
import { CandidateTray } from './CandidateTray'
import { ControlSurface } from './ControlSurface'
import { DirectionPanel } from './DirectionPanel'
import { PronunciationPanel } from './PronunciationPanel'
import { QualityPanel } from './QualityPanel'
import { VoiceLibrary } from './VoiceLibrary'
import { deepClone, errorMessage, mergeParameters, setPath } from './utils'

interface VoiceCityStudioProps {
  onUseVoice: (selection: VoiceCitySelection) => void
  onReturnToProduction?: () => void
  manuscriptText?: string
}

type WorkspaceTab = 'design' | 'direction' | 'pronunciation' | 'automation' | 'quality' | 'safety'
type RightTab = 'candidates' | 'library'

const modeIcon = (mode: VoiceCityMode) => mode === 'simple' ? SlidersHorizontal : mode === 'studio' ? Dna : mode === 'laboratory' ? FlaskConical : Beaker

const DEFAULT_DIRECTION_PLAN: VoiceDirectionPlan = {
  enabled: true,
  automatic_dialogue_detection: true,
  unknown_dialogue_policy: 'narrator',
  director_instructions: '',
  default_dialogue_overrides: {
    narration: { dialogue_lift: 0.2 },
    performance: { energy: 0.55, conversationality: 0.7, emotional_intensity: 0.5 },
  },
  chapter_styles: {},
  scene_styles: {},
  cast: [],
}

export function VoiceCityStudio({ onUseVoice, onReturnToProduction, manuscriptText = '' }: VoiceCityStudioProps) {
  const [mode, setMode] = useState<VoiceCityMode>('studio')
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('design')
  const [rightTab, setRightTab] = useState<RightTab>('candidates')
  const [schema, setSchema] = useState<VoiceCitySchema | null>(null)
  const [automationSchema, setAutomationSchema] = useState<VoiceCitySchema | null>(null)
  const [capabilities, setCapabilities] = useState<VoiceCityCapabilities | null>(null)
  const [scripts, setScripts] = useState<AuditionScript[]>([])
  const [presets, setPresets] = useState<VoiceCityPreset[]>([])
  const [voices, setVoices] = useState<VoiceCityVoice[]>([])
  const [selectedVoice, setSelectedVoice] = useState<VoiceCityVoice | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<VoiceCityVersion | null>(null)
  const [parameters, setParameters] = useState<VoiceParameters>({})
  const [past, setPast] = useState<VoiceParameters[]>([])
  const [future, setFuture] = useState<VoiceParameters[]>([])
  const [lockedPaths, setLockedPaths] = useState<Set<string>>(new Set())
  const [candidates, setCandidates] = useState<VoiceCityCandidate[]>([])
  const [selectedCandidate, setSelectedCandidate] = useState<VoiceCityCandidate | null>(null)
  const [preview, setPreview] = useState<VoicePreview | null>(null)
  const [description, setDescription] = useState('Mature, reassuring narrator with a low center pitch, restrained emotion, warm resonance, precise diction, and subtle British influence.')
  const [mutationRequest, setMutationRequest] = useState('warmer, 15 percent older, less nasal, and slightly more authoritative')
  const [candidateCount, setCandidateCount] = useState(4)
  const [breedA, setBreedA] = useState('')
  const [breedB, setBreedB] = useState('')
  const [breedWeight, setBreedWeight] = useState(70)
  const [pronunciations, setPronunciations] = useState<PronunciationRule[]>([])
  const [automation, setAutomation] = useState<AutomationTrack[]>([])
  const [qualityHistory, setQualityHistory] = useState<Array<Record<string, unknown>>>([])
  const [comparison, setComparison] = useState<Record<string, any> | null>(null)
  const [optimizationJob, setOptimizationJob] = useState<VoiceCityGenerationJob | null>(null)
  const [directionPlan, setDirectionPlan] = useState<VoiceDirectionPlan>(DEFAULT_DIRECTION_PLAN)
  const [directionAnalysis, setDirectionAnalysis] = useState<VoiceDirectionAnalysis | null>(null)
  const [directionBusy, setDirectionBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const currentSourceLabel = selectedCandidate?.name || (selectedVoice && selectedVersion ? `${selectedVoice.name} V${selectedVersion.version_number}` : '')

  const notify = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(current => current === message ? null : current), 3500)
  }
  const fail = (value: unknown) => setError(errorMessage(value))

  const loadVoices = useCallback(async (selectId?: string) => {
    const list = await voiceCityAPI.listVoices()
    setVoices(list)
    const targetId = selectId || selectedVoice?.id
    if (targetId) {
      const summary = list.find(voice => voice.id === targetId)
      if (summary) setSelectedVoice(current => current?.id === targetId ? { ...current, ...summary } : summary)
    }
  }, [selectedVoice?.id])

  useEffect(() => {
    setBusy(true)
    Promise.all([
      voiceCityAPI.capabilities(),
      voiceCityAPI.auditionScripts(),
      voiceCityAPI.listPresets(),
      voiceCityAPI.listVoices(),
      voiceCityAPI.schema('automation'),
    ]).then(([caps, auditionScripts, presetList, voiceList, automationContract]) => {
      setCapabilities(caps)
      setScripts(auditionScripts)
      setPresets(presetList)
      setVoices(voiceList)
      setAutomationSchema(automationContract)
    }).catch(fail).finally(() => setBusy(false))
  }, [])

  useEffect(() => {
    const requested = mode === 'automation' ? 'laboratory' : mode
    voiceCityAPI.schema(requested).then(contract => {
      setSchema(contract)
      setParameters(current => Object.keys(current).length ? current : deepClone(contract.defaults))
    }).catch(fail)
  }, [mode])

  useEffect(() => {
    if (!optimizationJob || !['queued', 'running'].includes(optimizationJob.status)) return
    let canceled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const next = await voiceCityAPI.getGenerationJob(optimizationJob.id)
        if (canceled) return
        setOptimizationJob(next)
        if (next.status === 'succeeded') {
          const voiceId = next.voice_id
          if (voiceId) {
            const [full, list] = await Promise.all([voiceCityAPI.getVoice(voiceId), voiceCityAPI.listVoices()])
            if (canceled) return
            setVoices(list)
            setSelectedVoice(full)
            setSelectedVersion(full.current_version)
            setParameters(deepClone(full.current_version?.parameters || schema?.defaults || {}))
            setSelectedCandidate(null)
            setPast([]); setFuture([])
          }
          notify('Persistent synthetic identity optimization completed as a new immutable version.')
          return
        }
        if (next.status === 'failed') {
          setError(next.error || 'Persistent identity optimization failed')
          return
        }
        if (next.status === 'canceled') {
          notify('Persistent identity optimization canceled.')
          return
        }
        timer = window.setTimeout(poll, 1600)
      } catch (value) {
        if (!canceled) fail(value)
      }
    }

    timer = window.setTimeout(poll, 700)
    return () => { canceled = true; if (timer) window.clearTimeout(timer) }
    // Polling is intentionally keyed to the durable job id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizationJob?.id])

  const commitParameters = (next: VoiceParameters) => {
    setPast(items => [...items.slice(-49), deepClone(parameters)])
    setFuture([])
    setParameters(next)
    setPreview(null)
  }

  const undo = () => {
    const previous = past[past.length - 1]
    if (!previous) return
    setPast(items => items.slice(0, -1))
    setFuture(items => [deepClone(parameters), ...items.slice(0, 49)])
    setParameters(deepClone(previous))
    setPreview(null)
  }
  const redo = () => {
    const next = future[0]
    if (!next) return
    setFuture(items => items.slice(1))
    setPast(items => [...items.slice(-49), deepClone(parameters)])
    setParameters(deepClone(next))
    setPreview(null)
  }

  const selectVoice = async (voice: VoiceCityVoice) => {
    setBusy(true)
    setError(null)
    try {
      const full = await voiceCityAPI.getVoice(voice.id)
      setSelectedVoice(full)
      setSelectedVersion(full.current_version)
      setParameters(deepClone(full.current_version?.parameters || schema?.defaults || {}))
      setPast([]); setFuture([]); setSelectedCandidate(null); setPreview(null); setRightTab('library')
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const createVoice = async (name: string) => {
    setBusy(true); setError(null)
    try {
      const voice = await voiceCityAPI.createVoice({ name, parameters: Object.keys(parameters).length ? parameters : schema?.defaults })
      await loadVoices(voice.id)
      await selectVoice(voice)
      notify(`${voice.name} was created with an immutable V1.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const saveVersion = async () => {
    if (!selectedVoice || !selectedVersion) return
    setBusy(true); setError(null)
    try {
      await voiceCityAPI.saveVersion(selectedVoice.id, {
        parameters,
        change_note: `Saved from ${mode} mode`,
        expected_current_version_id: selectedVersion.id,
      })
      const full = await voiceCityAPI.getVoice(selectedVoice.id)
      setSelectedVoice(full); setSelectedVersion(full.current_version); setParameters(deepClone(full.current_version?.parameters || parameters)); setPast([]); setFuture([])
      await loadVoices(full.id)
      notify(`${full.name} V${full.current_version?.version_number} saved.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const generate = async () => {
    setBusy(true); setError(null); setComparison(null)
    try {
      const result = await voiceCityAPI.generate({ description, count: candidateCount, locked_paths: [...lockedPaths] })
      setCandidates(result.candidates); setSelectedCandidate(result.candidates[0] || null); setRightTab('candidates')
      if (result.candidates[0]) setParameters(deepClone(result.candidates[0].parameters))
      notify(`${result.candidates.length} deterministic synthetic candidates generated.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const mutate = async () => {
    if (!selectedVersion) return
    setBusy(true); setError(null); setComparison(null)
    try {
      const result = await voiceCityAPI.mutate(selectedVersion.id, { request: mutationRequest, locked_paths: [...lockedPaths] })
      setCandidates(result.candidates); setSelectedCandidate(result.candidates[0] || null); setRightTab('candidates')
      if (result.candidates[0]) setParameters(deepClone(result.candidates[0].parameters))
      notify('A new mutation family was generated while preserving locked characteristics.')
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const breed = async () => {
    if (!breedA || !breedB || breedA === breedB) return
    setBusy(true); setError(null); setComparison(null)
    try {
      const result = await voiceCityAPI.breed({ version_a_id: breedA, version_b_id: breedB, weight_a: breedWeight / 100, locked_from_a: [...lockedPaths] })
      setCandidates(result.candidates); setSelectedCandidate(result.candidates[0] || null); setRightTab('candidates')
      if (result.candidates[0]) setParameters(deepClone(result.candidates[0].parameters))
      notify(`Voice DNA blended at ${breedWeight}/${100 - breedWeight}.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const selectCandidate = (candidate: VoiceCityCandidate) => {
    setSelectedCandidate(candidate); setParameters(deepClone(candidate.parameters)); setPreview(null)
  }

  const acceptCandidate = async (candidate: VoiceCityCandidate) => {
    setBusy(true); setError(null)
    try {
      const voice = await voiceCityAPI.acceptCandidate(candidate.id, selectedVoice
        ? { voice_id: selectedVoice.id, change_note: `Accepted ${candidate.name}` }
        : { name: candidate.name, change_note: 'Accepted generated candidate' })
      setCandidates(items => items.map(item => item.id === candidate.id ? { ...item, status: 'accepted' } : item))
      await loadVoices(voice.id)
      await selectVoice(voice)
      notify(`${candidate.name} was saved as an immutable voice version.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const rejectCandidate = async (candidate: VoiceCityCandidate) => {
    setBusy(true)
    try {
      await voiceCityAPI.rejectCandidate(candidate.id, 'Rejected in Candidate Tray')
      setCandidates(items => items.filter(item => item.id !== candidate.id))
      if (selectedCandidate?.id === candidate.id) setSelectedCandidate(null)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const renderPreview = useCallback(async (options: { scriptId?: string; text?: string; loudnessMatch: boolean }, explicitCandidate?: VoiceCityCandidate) => {
    const candidate = explicitCandidate || selectedCandidate
    if (!candidate && !selectedVersion) return
    setPreviewBusy(true); setError(null)
    try {
      const result = await voiceCityAPI.preview({
        candidate_id: candidate?.id,
        voice_version_id: candidate ? undefined : selectedVersion?.id,
        overrides: candidate ? undefined : parameters,
        script_id: options.scriptId,
        text: options.text,
        loudness_match: options.loudnessMatch,
      })
      setPreview(result)
    } catch (value) { fail(value) } finally { setPreviewBusy(false) }
  }, [selectedCandidate, selectedVersion, parameters])

  const compareCandidates = async (items: VoiceCityCandidate[], blind: boolean) => {
    setPreviewBusy(true); setError(null)
    try {
      const result = await voiceCityAPI.compareAuditions({
        sources: items.map(item => ({ candidate_id: item.id })),
        script_id: scripts[0]?.id,
        blind,
        segment_mode: 'whole',
      })
      setComparison(result); notify(blind ? 'Blind comparison rendered. Reveal mapping is retained for the result.' : 'A/B comparison rendered.')
    } catch (value) { fail(value) } finally { setPreviewBusy(false) }
  }

  const applyPreset = (preset: VoiceCityPreset) => {
    commitParameters(mergeParameters(schema?.defaults || {}, preset.parameters))
    setSelectedCandidate(null)
    notify(`${preset.name} applied as a starting point.`)
  }

  const optimizeIdentity = async (version: VoiceCityVersion) => {
    if (!capabilities?.persistent_identity_optimization) {
      setError('Persistent identity optimization requires a configured Voice City model server.')
      return
    }
    setError(null)
    try {
      const job = await voiceCityAPI.optimizeVersion(version.id)
      setOptimizationJob(job)
      notify(`Persistent identity optimization queued for V${version.version_number}.`)
    } catch (value) { fail(value) }
  }

  const cancelOptimization = async (job: VoiceCityGenerationJob) => {
    try {
      setOptimizationJob(await voiceCityAPI.cancelGenerationJob(job.id))
      notify('Cancellation requested for persistent identity optimization.')
    } catch (value) { fail(value) }
  }

  const rollback = async (voice: VoiceCityVoice, version: VoiceCityVersion) => {
    if (!window.confirm(`Roll ${voice.name} back to V${version.version_number}? A new rollback version will preserve history.`)) return
    setBusy(true)
    try { const full = await voiceCityAPI.rollback(voice.id, version.id); await loadVoices(full.id); await selectVoice(full); notify('Rollback saved as a new immutable version.') } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const exportRecipe = async (voice: VoiceCityVoice) => {
    try {
      const recipe = await voiceCityAPI.exportRecipe(voice.id)
      const url = URL.createObjectURL(new Blob([JSON.stringify(recipe, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${voice.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-voice-recipe.json`; anchor.click(); URL.revokeObjectURL(url)
    } catch (value) { fail(value) }
  }

  const revokeVoice = async (voice: VoiceCityVoice) => {
    if (!window.confirm(`Revoke ${voice.name}? It will be blocked from new production use.`)) return
    try { await voiceCityAPI.revoke(voice.id, 'Revoked from Voice City Studio'); await loadVoices(); notify(`${voice.name} revoked.`) } catch (value) { fail(value) }
  }
  const deleteVoice = async (voice: VoiceCityVoice) => {
    if (!window.confirm(`Delete ${voice.name}? Existing audit history remains, but the voice is no longer available.`)) return
    try { await voiceCityAPI.deleteVoice(voice.id); if (selectedVoice?.id === voice.id) { setSelectedVoice(null); setSelectedVersion(null); setParameters(deepClone(schema?.defaults || {})) } await loadVoices(); notify(`${voice.name} deleted.`) } catch (value) { fail(value) }
  }

  const analyzeDirection = async (sourceText: string) => {
    setDirectionBusy(true); setError(null)
    try {
      const analysis = await voiceCityAPI.analyzeDirection(sourceText)
      setDirectionAnalysis(analysis)
      notify(`Detected ${analysis.speakers.length} attributed speakers across ${analysis.scene_count} scene${analysis.scene_count === 1 ? '' : 's'}.`)
    } catch (value) { fail(value) } finally { setDirectionBusy(false) }
  }

  const applyVoiceSelection = async (selection: VoiceCitySelection) => {
    setBusy(true); setError(null)
    try {
      const validated = await voiceCityAPI.validateDirection(directionPlan, selectedVersion?.seed)
      onUseVoice({ ...selection, directionPlan: validated })
      notify(`${selection.displayName} V${selection.versionNumber} and its direction plan were selected for audiobook production.`)
    } catch (value) { fail(value) } finally { setBusy(false) }
  }

  const refreshPronunciations = async () => {
    try { setPronunciations(await voiceCityAPI.listPronunciations(selectedVoice?.id)) } catch (value) { fail(value) }
  }
  const refreshAutomation = async () => {
    if (!selectedVoice) return setAutomation([])
    try { setAutomation(await voiceCityAPI.listAutomation(selectedVoice.id)) } catch (value) { fail(value) }
  }
  const refreshQuality = async () => {
    if (!selectedVersion) return setQualityHistory([])
    try { setQualityHistory(await voiceCityAPI.qualityHistory(selectedVersion.id)) } catch (value) { fail(value) }
  }

  const versionOptions = useMemo(() => voices.flatMap(voice => {
    const versions = voice.versions?.length ? voice.versions : voice.current_version ? [voice.current_version] : []
    return versions.map(version => ({ id: version.id, label: `${voice.name} V${version.version_number}` }))
  }), [voices])

  const ModeIcon = modeIcon(mode)

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-800 bg-slate-950 text-white">
        <div className="mx-auto max-w-[1680px] px-4 py-4 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-gradient-to-br from-cyan-400 to-fuchsia-500 p-2.5"><Dna className="h-6 w-6 text-slate-950" /></div>
              <div><p className="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-300">ACX City</p><h1 className="text-2xl font-bold">Voice City</h1></div>
              <span className="hidden rounded-full border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 sm:inline">Synthetic-only safety mode</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {onReturnToProduction && <button type="button" onClick={onReturnToProduction} className="flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-900"><ChevronLeft className="h-4 w-4" /> Production</button>}
              <button type="button" onClick={undo} disabled={!past.length} className="rounded-lg border border-slate-700 p-2 disabled:opacity-30" aria-label="Undo"><Undo2 className="h-4 w-4" /></button>
              <button type="button" onClick={redo} disabled={!future.length} className="rounded-lg border border-slate-700 p-2 disabled:opacity-30" aria-label="Redo"><Redo2 className="h-4 w-4" /></button>
              <button type="button" onClick={saveVersion} disabled={!selectedVoice || busy} className="flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-40"><Save className="h-4 w-4" /> Save version</button>
              <button type="button" onClick={generate} disabled={busy || !description.trim()} className="flex items-center gap-2 rounded-lg bg-fuchsia-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"><WandSparkles className="h-4 w-4" /> Generate variants</button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {(['simple', 'studio', 'laboratory', 'automation'] as VoiceCityMode[]).map(item => {
              const Icon = modeIcon(item)
              const count = schema?.modes.find(value => value.id === item)?.control_count || automationSchema?.modes.find(value => value.id === item)?.control_count
              return <button key={item} type="button" onClick={() => { setMode(item); if (item === 'automation') setWorkspaceTab('automation'); else setWorkspaceTab('design') }} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm capitalize ${mode === item ? 'bg-cyan-400 font-semibold text-slate-950' : 'text-slate-300 hover:bg-slate-900'}`}><Icon className="h-4 w-4" /> {item}<span className="text-[10px] opacity-70">{count}</span></button>
            })}
            <div className="ml-auto flex items-center gap-2 text-xs text-slate-400"><ModeIcon className="h-4 w-4" /> Schema {schema?.schema_version || '…'} · deterministic seed {String(parameters.seed || '—')}</div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1680px] px-4 py-5 sm:px-6">
        {(notice || error) && <div className={`mb-4 flex items-start justify-between rounded-xl border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}><span>{error || notice}</span><button type="button" onClick={() => { setError(null); setNotice(null) }}><span className="sr-only">Dismiss</span>×</button></div>}

        <div className="mb-4 grid gap-3 lg:grid-cols-[1fr_auto]">
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles className="h-4 w-4 text-fuchsia-600" />
              <input value={description} onChange={event => setDescription(event.target.value)} className="min-w-[260px] flex-1 border-0 bg-transparent text-sm focus:outline-none" aria-label="Voice description" />
              <select value={candidateCount} onChange={event => setCandidateCount(Number(event.target.value))} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs"><option value={4}>4 candidates</option><option value={6}>6 candidates</option><option value={8}>8 candidates</option></select>
              <button type="button" onClick={generate} disabled={busy} className="rounded-lg bg-fuchsia-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Generate</button>
            </div>
          </div>
          <select onChange={event => { const preset = presets.find(item => item.id === event.target.value); if (preset) applyPreset(preset); event.currentTarget.value = '' }} defaultValue="" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"><option value="" disabled>Apply a preset…</option>{presets.map(preset => <option key={preset.id} value={preset.id}>{preset.category} — {preset.name}</option>)}</select>
        </div>

        <div className="mb-4 flex overflow-x-auto rounded-xl border border-slate-200 bg-white p-1">
          {([
            ['design', 'Voice DNA', Dna], ['direction', 'Casting & direction', BookOpen], ['pronunciation', 'Pronunciation', Volume2], ['automation', 'Automation', Beaker], ['quality', 'Readiness', ShieldCheck], ['safety', 'Safety & provenance', LockKeyhole],
          ] as const).map(([id, label, Icon]) => <button key={id} type="button" onClick={() => setWorkspaceTab(id)} className={`flex shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-sm ${workspaceTab === id ? 'bg-slate-950 font-semibold text-white' : 'text-slate-600 hover:bg-slate-100'}`}><Icon className="h-4 w-4" />{label}</button>)}
        </div>

        {workspaceTab === 'design' && (
          <div className="grid gap-4 xl:grid-cols-[minmax(360px,1.05fr)_minmax(420px,1.2fr)_minmax(310px,.8fr)]">
            <div className="max-h-[calc(100vh-275px)] overflow-y-auto pr-1"><ControlSurface schema={schema} parameters={parameters} lockedPaths={lockedPaths} onChange={next => commitParameters(next)} onToggleLock={path => setLockedPaths(current => { const next = new Set(current); if (next.has(path)) next.delete(path); else next.add(path); return next })} onResetControl={control => commitParameters(setPath(parameters, control.path, control.default))} /></div>

            <div className="space-y-4">
              <AuditionRoom scripts={scripts} preview={preview} busy={previewBusy} sourceLabel={currentSourceLabel} onPreview={options => renderPreview(options)} onClear={() => setPreview(null)} />

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-900">Mutate the selected identity</h2>
                <div className="mt-3 flex gap-2"><input value={mutationRequest} onChange={event => setMutationRequest(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" /><button type="button" disabled={!selectedVersion || busy} onClick={mutate} className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Mutate</button></div>
                <p className="mt-2 text-xs text-slate-500">Locked characteristics are preserved. Identity remains recognizable while performance and requested traits move.</p>
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2"><GitMerge className="h-4 w-4 text-fuchsia-600" /><h2 className="text-sm font-semibold text-slate-900">Breed two licensed synthetic versions</h2></div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2"><select value={breedA} onChange={event => setBreedA(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="">Voice A…</option>{versionOptions.map(option => <option key={`a-${option.id}`} value={option.id}>{option.label}</option>)}</select><select value={breedB} onChange={event => setBreedB(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="">Voice B…</option>{versionOptions.map(option => <option key={`b-${option.id}`} value={option.id}>{option.label}</option>)}</select></div>
                <div className="mt-3 flex items-center gap-3"><span className="text-xs text-slate-500">A {breedWeight}%</span><input type="range" min={5} max={95} value={breedWeight} onChange={event => setBreedWeight(Number(event.target.value))} className="flex-1 accent-fuchsia-600" /><span className="text-xs text-slate-500">B {100 - breedWeight}%</span><button type="button" disabled={!breedA || !breedB || breedA === breedB || busy} onClick={breed} className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Blend</button></div>
              </section>

              {comparison && <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-4"><div className="flex items-center justify-between"><strong className="text-sm text-cyan-950">{comparison.blind ? 'Blind' : 'A/B'} comparison</strong><button type="button" onClick={() => setComparison(null)} className="text-cyan-700">×</button></div><div className="mt-3 space-y-3">{(comparison.sources || []).map((source: any, index: number) => <div key={source.candidate_id || source.voice_version_id || index} className="rounded-lg bg-white p-3"><p className="mb-2 text-xs font-semibold text-slate-700">{source.blind_label || source.display_name || `Sample ${index + 1}`}</p><audio controls src={source.previews?.[0]?.url} className="w-full" /></div>)}</div>{comparison.blind && comparison.reveal?.length > 0 && <details className="mt-3 text-xs"><summary className="cursor-pointer font-semibold text-cyan-900">Reveal identities</summary><div className="mt-2">{comparison.reveal.map((item: any) => <p key={item.label}>{item.label}: {item.display_name}</p>)}</div></details>}</section>}
            </div>

            <aside className="min-h-[520px] rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-4 grid grid-cols-2 rounded-lg bg-slate-100 p-1"><button type="button" onClick={() => setRightTab('candidates')} className={`flex items-center justify-center gap-1 rounded-md px-2 py-2 text-xs font-semibold ${rightTab === 'candidates' ? 'bg-white shadow' : 'text-slate-500'}`}><Sparkles className="h-3.5 w-3.5" /> Candidates ({candidates.length})</button><button type="button" onClick={() => setRightTab('library')} className={`flex items-center justify-center gap-1 rounded-md px-2 py-2 text-xs font-semibold ${rightTab === 'library' ? 'bg-white shadow' : 'text-slate-500'}`}><Library className="h-3.5 w-3.5" /> Library ({voices.length})</button></div>
              <div className="max-h-[calc(100vh-330px)] overflow-y-auto pr-1">{rightTab === 'candidates' ? <CandidateTray candidates={candidates} selectedCandidateId={selectedCandidate?.id || null} onSelect={selectCandidate} onPreview={candidate => { selectCandidate(candidate); renderPreview({ scriptId: scripts[0]?.id, loudnessMatch: true }, candidate) }} onAccept={acceptCandidate} onReject={rejectCandidate} onCompare={compareCandidates} /> : <VoiceLibrary voices={voices} selectedVoiceId={selectedVoice?.id || null} busy={busy} optimizationEnabled={Boolean(capabilities?.persistent_identity_optimization)} optimizationJob={optimizationJob} onSelect={selectVoice} onCreate={createVoice} onRollback={rollback} onOptimize={optimizeIdentity} onCancelOptimization={cancelOptimization} onUse={selection => { void applyVoiceSelection(selection) }} onExport={exportRecipe} onRevoke={revokeVoice} onDelete={deleteVoice} />}</div>
            </aside>
          </div>
        )}

        {workspaceTab === 'direction' && <DirectionPanel manuscriptText={manuscriptText} voices={voices} plan={directionPlan} analysis={directionAnalysis} busy={directionBusy} onAnalyze={analyzeDirection} onChange={setDirectionPlan} />}

        {workspaceTab === 'pronunciation' && <PronunciationPanel voiceId={selectedVoice?.id || null} rules={pronunciations} onRefresh={refreshPronunciations} onCreate={async rule => { try { await voiceCityAPI.createPronunciation(rule); await refreshPronunciations(); notify('Pronunciation rule saved.') } catch (value) { fail(value) } }} onUpdate={async (id, patch) => { try { await voiceCityAPI.updatePronunciation(id, patch); await refreshPronunciations() } catch (value) { fail(value) } }} onDelete={async id => { try { await voiceCityAPI.deletePronunciation(id); await refreshPronunciations() } catch (value) { fail(value) } }} />}

        {workspaceTab === 'automation' && <AutomationPanel voiceId={selectedVoice?.id || null} controls={automationSchema?.controls || []} tracks={automation} onRefresh={refreshAutomation} onCreate={async payload => { if (!selectedVoice) return; try { await voiceCityAPI.createAutomation(selectedVoice.id, payload); await refreshAutomation(); notify('Automation track saved.') } catch (value) { fail(value) } }} onUpdate={async (id, patch) => { try { await voiceCityAPI.updateAutomation(id, patch); await refreshAutomation() } catch (value) { fail(value) } }} onDelete={async id => { try { await voiceCityAPI.deleteAutomation(id); await refreshAutomation() } catch (value) { fail(value) } }} />}

        {workspaceTab === 'quality' && <QualityPanel version={selectedVersion} history={qualityHistory} onRefresh={refreshQuality} onRecord={async (metrics: QualityMetrics, durationTestedS: number, notes: string) => { if (!selectedVersion) return; try { const result = await voiceCityAPI.recordQuality(selectedVersion.id, { metrics, duration_tested_s: durationTestedS, notes }); await refreshQuality(); await loadVoices(); notify(result.report?.production_ready ? 'Version passed every production-readiness gate.' : 'Evaluation recorded; one or more gates remain open.') } catch (value) { fail(value) } }} />}

        {workspaceTab === 'safety' && (
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald-600" /><h2 className="font-semibold">Synthetic-first ownership controls</h2></div><div className="mt-4 space-y-3 text-sm text-slate-600">{[
              ['Named-person imitation prompts are blocked', true],
              ['Every version stores creation provenance and a deterministic fingerprint', true],
              ['Every preview stores an audio fingerprint and provenance sidecar', capabilities?.provenance_sidecars],
              ['Character casting stores immutable per-character version snapshots', capabilities?.character_casting],
              ['Dialogue analysis casts only evidence-backed speaker attributions', capabilities?.automatic_dialogue_detection],
              ['Chapter, scene, sentence, and character direction are bounded to performance controls', capabilities?.scene_and_sentence_direction],
              ['Organization administrators can revoke a voice', true],
              ['Anonymous/public model exports are blocked', !capabilities?.anonymous_model_export && !capabilities?.public_model_export],
              ['Reference-audio workflow is disabled by default', !capabilities?.reference_voice_creation],
              ['Protected profile registry configured', capabilities?.protected_profile_registry_configured],
              [`Persistent identity model server (${capabilities?.model_server_protocol || 'voice-city-http-v1'}) configured`, capabilities?.persistent_identity_optimization],
            ].map(([label, passed]) => <div key={String(label)} className="flex items-center gap-3 rounded-lg bg-slate-50 p-3"><span className={`flex h-5 w-5 items-center justify-center rounded-full ${passed ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{passed ? <Check className="h-3 w-3" /> : '!'}</span>{String(label)}</div>)}</div></section>
            <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">What may leave Voice City</h2><p className="mt-2 text-sm leading-6 text-slate-600">The export action produces a parameter recipe and provenance record—not anonymous neural model weights. Production jobs bind immutable narrator and character-version snapshots, the complete direction plan, pronunciation dictionaries, automation configuration, provider/model mappings, and render fingerprints so later edits cannot silently alter a book.</p><div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><strong>Reference voices remain feature-gated.</strong><p className="mt-1 text-xs leading-5">Consent documents, talent agreements, identity verification, speaker authorization, revocation, audit evidence, and protected-person screening are required before that workflow can be enabled.</p></div></section>
          </div>
        )}
      </main>
    </div>
  )
}
