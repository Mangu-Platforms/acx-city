// Voice City shared type contracts.
//
// Shapes are derived from the backend serializers in
// backend/services/voice_city/service.py (serialize_voice / serialize_version /
// serialize_candidate / serialize_generation_job / readiness_report), the HTTP
// surface in backend/voice_city/api.py, the parameter contract in
// backend/services/voice_city/parameter_schema.py, and the consumers in
// App.tsx, VoiceCityStudio.tsx, DirectionPanel.tsx, and voiceCityApi.ts.

// ---------------------------------------------------------------------------
// Parameter documents
// ---------------------------------------------------------------------------

export type VoiceParameterValue = string | number | boolean | null

/** A (possibly nested) group of controls, e.g. identity.resonance.chest. */
export interface VoiceParameterGroup {
  [key: string]: VoiceParameterValue | VoiceParameterGroup
}

/**
 * A canonical Voice City parameter document keyed by group. The backend also
 * stores the bookkeeping keys "seed" (number) and "schema_version" (string) at
 * the top level; they are intentionally left to the index signature so that
 * group access by arbitrary string key (DirectionPanel / ControlSurface)
 * remains fully typed.
 */
export interface VoiceParameters {
  [group: string]: VoiceParameterGroup | undefined
}

// ---------------------------------------------------------------------------
// Parameter schema (GET /voice-city/schema)
// ---------------------------------------------------------------------------

export type VoiceCityMode = 'simple' | 'studio' | 'laboratory' | 'automation'

export interface VoiceCityModeInfo {
  id: VoiceCityMode
  label: string
  control_count: number
}

export interface VoiceCitySchemaGroup {
  id: string
  title: string
  order: number
  description: string
}

export type VoiceCityControlType = 'slider' | 'select' | 'toggle'

export interface VoiceCityControl {
  path: string
  label: string
  group: string
  control_type: VoiceCityControlType
  default: VoiceParameterValue
  minimum: number | null
  maximum: number | null
  step: number | null
  unit: string | null
  mode: VoiceCityMode
  description: string
  audible_impact: string
  options: string[]
  automatable: boolean
  aliases: string[]
  tags: string[]
}

export interface VoiceCitySchema {
  schema_version: string
  architecture: string
  modes: VoiceCityModeInfo[]
  groups: VoiceCitySchemaGroup[]
  controls: VoiceCityControl[]
  defaults: VoiceParameters
  constraints: string[]
}

// ---------------------------------------------------------------------------
// Capabilities (GET /voice-city/capabilities)
// ---------------------------------------------------------------------------

export interface VoiceCityCapabilities {
  synthetic_voice_creation: boolean
  reference_voice_creation: boolean
  voice_cloning: boolean
  anonymous_model_export: boolean
  public_model_export: boolean
  parameter_schema_version: string
  modes: VoiceCityModeInfo[]
  providers: Array<Record<string, unknown>>
  preview_max_characters: number
  production_snapshotting: boolean
  pronunciation_dictionary: boolean
  chapter_automation: boolean
  character_casting: boolean
  automatic_dialogue_detection: boolean
  scene_and_sentence_direction: boolean
  provenance_sidecars: boolean
  protected_profile_registry_configured: boolean
  persistent_identity_optimization: boolean
  model_server_protocol: string
}

// ---------------------------------------------------------------------------
// Voices and immutable versions
// ---------------------------------------------------------------------------

export type VoiceCityVoiceStatus = 'draft' | 'ready' | 'revoked' | 'deleted'
export type VoiceCityVersionStatus = 'draft' | 'ready' | 'production-ready'
export type VoiceCityVisibility = 'private' | 'organization'

export interface VoiceCityVersion {
  id: string
  voice_id: string
  version_number: number
  schema_version: string
  parameters: VoiceParameters
  default_style_parameters: VoiceParameters | null
  provider: string
  provider_voice_id: string | null
  model_revision: string | null
  seed: number
  quality_score: number | null
  consistency_score: number | null
  supported_languages: string[]
  status: VoiceCityVersionStatus
  fingerprint: string
  provenance: Record<string, unknown>
  change_note: string | null
  created_at: string | null
}

export interface VoiceCityVoice {
  id: string
  organization_id: string
  name: string
  description: string | null
  voice_type: string
  status: VoiceCityVoiceStatus
  provider: string
  model_family: string
  current_version_id: string | null
  visibility: VoiceCityVisibility
  safety_classification: string
  ownership_record: Record<string, unknown>
  export_restrictions: Record<string, unknown>
  tags: string[]
  default_use_cases: string[]
  created_at: string | null
  updated_at: string | null
  revoked_at: string | null
  current_version: VoiceCityVersion | null
  /** Present on GET /voice-city/voices/:id responses only. */
  versions?: VoiceCityVersion[]
}

// ---------------------------------------------------------------------------
// Candidate generation (generate / mutate / breed)
// ---------------------------------------------------------------------------

export type VoiceCityCandidateStatus = 'candidate' | 'blocked' | 'accepted' | 'rejected'

export interface VoiceCityCandidate {
  id: string
  candidate_set_id: string
  ordinal: number
  name: string
  parameters: VoiceParameters
  provider: string
  provider_voice_id: string | null
  quality_score: number
  consistency_score: number
  uniqueness_score: number
  fingerprint: string
  status: VoiceCityCandidateStatus
  source_versions: string[]
  warnings: string[]
  created_at: string | null
}

export interface CandidateSetResponse {
  generation_job_id: string
  candidate_set_id: string
  operation: string
  candidates: VoiceCityCandidate[]
}

export type VoiceCityGenerationJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'

export interface VoiceCityGenerationJob {
  id: string
  voice_id: string | null
  operation: string
  status: VoiceCityGenerationJobStatus
  progress: number
  stage: string | null
  error: string | null
  request: Record<string, unknown> | null
  result: Record<string, unknown> | null
  attempts: number
  max_attempts: number
  available_at: string | null
  cancel_requested: boolean
  created_at: string | null
  updated_at: string | null
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

export interface VoiceCityPreset {
  id: string
  name: string
  description: string | null
  category: string
  is_template: boolean
  parameters: VoiceParameters
  source_voice_version_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

// ---------------------------------------------------------------------------
// Audition room
// ---------------------------------------------------------------------------

export interface AuditionScript {
  id: string
  category: string
  text: string
  title?: string
  name?: string
  description?: string
}

/**
 * POST /voice-city/previews response: preview row fields plus the renderer
 * result (signed audio URL, fingerprint, provenance sidecar reference).
 */
export interface VoicePreview {
  id: string
  status: string
  duration_s: number | null
  display_name?: string
  url?: string | null
  expires_in?: number
  text?: string
  script_id?: string | null
  provider?: string
  provider_voice_id?: string | null
  cache_hit?: boolean
  fingerprint?: string | null
  provenance?: Record<string, unknown> | null
  error?: string | null
}

// ---------------------------------------------------------------------------
// Pronunciation dictionary
// ---------------------------------------------------------------------------

export type PronunciationRuleKind = 'literal' | 'pattern'

export interface PronunciationRule {
  /** Absent while composing a new rule; always present on API responses. */
  id?: string
  /** null / absent = library-wide rule, otherwise scoped to one voice. */
  voice_id?: string | null
  pattern: string
  replacement: string
  language: string
  rule_type: PronunciationRuleKind
  priority: number
  case_sensitive: boolean
  enabled: boolean
  notes?: string | null
  created_at?: string | null
}

// ---------------------------------------------------------------------------
// Automation curves
// ---------------------------------------------------------------------------

export type AutomationScopeType = 'global' | 'chapter' | 'scene' | 'sentence' | 'character'
export type AutomationInterpolation = 'linear' | 'step' | 'smooth'

export interface AutomationKeyframe {
  /** Normalized position within the scope, 0..1. */
  at: number
  value: number
}

export interface AutomationTrack {
  id: string
  voice_id: string
  project_id: string | null
  scope_type: AutomationScopeType
  scope_key: string
  parameter_path: string
  keyframes: AutomationKeyframe[]
  interpolation: AutomationInterpolation
  enabled: boolean
}

/** Creation payload accepted by POST /voice-city/voices/:id/automation. */
export type AutomationTrackDraft = Omit<AutomationTrack, 'id' | 'voice_id' | 'project_id'> & {
  project_id?: string | null
}

// ---------------------------------------------------------------------------
// Production readiness
// ---------------------------------------------------------------------------

export interface QualityMetrics {
  identity_consistency: number
  pronunciation_accuracy: number
  chapter_timbre_stability: number
  emotional_controllability: number
  speaker_drift_events: number
  max_chapter_loudness_delta_db: number
  long_form_listening_passed: boolean
  similarity_screen_passed: boolean
}

export type QualityGateKey =
  | 'identity_consistency_30_minutes'
  | 'pronunciation_accuracy'
  | 'chapter_timbre_stability'
  | 'emotional_controllability'
  | 'no_speaker_drift'
  | 'loudness_consistency'
  | 'long_form_listening_evaluation'
  | 'duplicate_similarity_screening'

export interface QualityReadinessReport {
  production_ready: boolean
  checks: Record<QualityGateKey, boolean>
  passed: number
  required: number
  duration_tested_s: number
}

// ---------------------------------------------------------------------------
// Casting and direction
// ---------------------------------------------------------------------------

export interface VoiceDirectionSpeaker {
  name: string
  normalized_name?: string
  turns: number
  excerpts?: string[]
}

export interface VoiceDirectionSegment {
  index: number
  scene_index: number
  kind: 'narration' | 'dialogue'
  speaker: string | null
  text: string
  start?: number
  end?: number
  confidence?: number
  evidence?: string | null
}

export interface VoiceDirectionAnalysis {
  character_count: number
  segment_count: number
  dialogue_segment_count: number
  unattributed_dialogue_count: number
  scene_count: number
  speakers: VoiceDirectionSpeaker[]
  segments: VoiceDirectionSegment[]
  detector: string
  policy: string
}

export interface VoiceDirectionCastEntry {
  character_name: string
  normalized_name?: string
  aliases: string[]
  voice_version_id: string
  style_overrides: VoiceParameters
}

export interface VoiceDirectionPlan {
  enabled: boolean
  automatic_dialogue_detection: boolean
  unknown_dialogue_policy: 'narrator' | 'skip'
  director_instructions: string
  /** Populated by POST /voice-city/direction/validate. */
  director_parameter_patch?: VoiceParameters
  default_dialogue_overrides?: VoiceParameters
  /** Values are natural-language direction strings or sparse parameter patches. */
  chapter_styles: Record<string, unknown>
  scene_styles: Record<string, unknown>
  cast: VoiceDirectionCastEntry[]
  detector_version?: string
}

// ---------------------------------------------------------------------------
// Production hand-off (Voice City -> audiobook synthesis)
// ---------------------------------------------------------------------------

/**
 * What the studio hands back to production. voiceVersionId feeds
 * /api/synthesize voice_version_id; provider/providerVoiceId preselect the
 * catalog controls; directionPlan feeds voice_direction.
 */
export interface VoiceCitySelection {
  voiceId: string
  voiceVersionId: string
  provider: string
  providerVoiceId: string
  displayName: string
  versionNumber: number
  seed?: number
  directionPlan?: VoiceDirectionPlan
}
