import { api } from './api'
import type {
  AuditionScript,
  AutomationTrack,
  CandidateSetResponse,
  PronunciationRule,
  QualityMetrics,
  VoiceCityCandidate,
  VoiceCityCapabilities,
  VoiceDirectionAnalysis,
  VoiceDirectionPlan,
  VoiceCityGenerationJob,
  VoiceCityPreset,
  VoiceCitySchema,
  VoiceCityVoice,
  VoiceCityVersion,
  VoiceParameters,
  VoicePreview,
} from '../types/voice-city'

export const voiceCityAPI = {
  capabilities: async (): Promise<VoiceCityCapabilities> => {
    const response = await api.get<VoiceCityCapabilities>('/voice-city/capabilities')
    return response.data
  },

  schema: async (mode: string, search?: string): Promise<VoiceCitySchema> => {
    const response = await api.get<VoiceCitySchema>('/voice-city/schema', { params: { mode, search } })
    return response.data
  },

  auditionScripts: async (): Promise<AuditionScript[]> => {
    const response = await api.get<AuditionScript[]>('/voice-city/audition-scripts')
    return response.data
  },

  analyzeDirection: async (text: string): Promise<VoiceDirectionAnalysis> => {
    const response = await api.post<VoiceDirectionAnalysis>('/voice-city/direction/analyze', { text })
    return response.data
  },

  validateDirection: async (plan: VoiceDirectionPlan, seed?: number): Promise<VoiceDirectionPlan> => {
    const response = await api.post<VoiceDirectionPlan>('/voice-city/direction/validate', { plan, seed })
    return response.data
  },

  listVoices: async (): Promise<VoiceCityVoice[]> => {
    const response = await api.get<VoiceCityVoice[]>('/voice-city/voices')
    return response.data
  },

  getVoice: async (voiceId: string): Promise<VoiceCityVoice> => {
    const response = await api.get<VoiceCityVoice>(`/voice-city/voices/${voiceId}`)
    return response.data
  },

  createVoice: async (payload: {
    name: string
    description?: string
    parameters?: VoiceParameters
    seed?: number
    provider?: string
    provider_voice_id?: string
    tags?: string[]
    default_use_cases?: string[]
  }): Promise<VoiceCityVoice> => {
    const response = await api.post<VoiceCityVoice>('/voice-city/voices', payload)
    return response.data
  },

  updateVoice: async (voiceId: string, payload: Partial<Pick<VoiceCityVoice, 'name' | 'description' | 'tags' | 'default_use_cases' | 'visibility'>>): Promise<VoiceCityVoice> => {
    const response = await api.patch<VoiceCityVoice>(`/voice-city/voices/${voiceId}`, payload)
    return response.data
  },

  saveVersion: async (voiceId: string, payload: {
    parameters: VoiceParameters
    change_note?: string
    provider_voice_id?: string
    expected_current_version_id?: string
  }): Promise<VoiceCityVersion> => {
    const response = await api.post<VoiceCityVersion>(`/voice-city/voices/${voiceId}/versions`, payload)
    return response.data
  },

  rollback: async (voiceId: string, versionId: string): Promise<VoiceCityVoice> => {
    const response = await api.post<VoiceCityVoice>(`/voice-city/voices/${voiceId}/rollback`, { version_id: versionId })
    return response.data
  },

  revoke: async (voiceId: string, reason?: string): Promise<VoiceCityVoice> => {
    const response = await api.post<VoiceCityVoice>(`/voice-city/voices/${voiceId}/revoke`, { reason })
    return response.data
  },

  deleteVoice: async (voiceId: string): Promise<void> => {
    await api.delete(`/voice-city/voices/${voiceId}`)
  },

  exportRecipe: async (voiceId: string, versionId?: string): Promise<Record<string, unknown>> => {
    const response = await api.get(`/voice-city/voices/${voiceId}/export`, { params: { version_id: versionId } })
    return response.data
  },

  generate: async (payload: {
    description: string
    provider?: string
    count?: number
    seed?: number
    locked_paths?: string[]
  }): Promise<CandidateSetResponse> => {
    const response = await api.post<CandidateSetResponse>('/voice-city/generate', payload)
    return response.data
  },

  mutate: async (versionId: string, payload: {
    request: string
    seed?: number
    locked_paths?: string[]
  }): Promise<CandidateSetResponse> => {
    const response = await api.post<CandidateSetResponse>(`/voice-city/versions/${versionId}/mutate`, payload)
    return response.data
  },

  optimizeVersion: async (versionId: string): Promise<VoiceCityGenerationJob> => {
    const response = await api.post<VoiceCityGenerationJob>(`/voice-city/versions/${versionId}/optimize`)
    return response.data
  },

  getGenerationJob: async (jobId: string): Promise<VoiceCityGenerationJob> => {
    const response = await api.get<VoiceCityGenerationJob>(`/voice-city/generation-jobs/${jobId}`)
    return response.data
  },

  cancelGenerationJob: async (jobId: string): Promise<VoiceCityGenerationJob> => {
    const response = await api.post<VoiceCityGenerationJob>(`/voice-city/generation-jobs/${jobId}/cancel`)
    return response.data
  },

  breed: async (payload: {
    version_a_id: string
    version_b_id: string
    weight_a: number
    seed?: number
    locked_from_a?: string[]
  }): Promise<CandidateSetResponse> => {
    const response = await api.post<CandidateSetResponse>('/voice-city/breed', payload)
    return response.data
  },

  compareCandidates: async (candidateIds: string[]): Promise<Record<string, unknown>> => {
    const response = await api.post('/voice-city/candidates/compare', { candidate_ids: candidateIds })
    return response.data
  },

  acceptCandidate: async (candidateId: string, payload: {
    voice_id?: string
    name?: string
    change_note?: string
  }): Promise<VoiceCityVoice> => {
    const response = await api.post<VoiceCityVoice>(`/voice-city/candidates/${candidateId}/accept`, payload)
    return response.data
  },

  rejectCandidate: async (candidateId: string, reason?: string): Promise<VoiceCityCandidate> => {
    const response = await api.post<VoiceCityCandidate>(`/voice-city/candidates/${candidateId}/reject`, { reason })
    return response.data
  },

  preview: async (payload: {
    voice_version_id?: string
    candidate_id?: string
    text?: string
    script_id?: string
    overrides?: VoiceParameters
    loudness_match?: boolean
  }): Promise<VoicePreview> => {
    const response = await api.post<VoicePreview>('/voice-city/previews', payload)
    return response.data
  },

  compareAuditions: async (payload: {
    sources: { voice_version_id?: string; candidate_id?: string; overrides?: VoiceParameters }[]
    text?: string
    script_id?: string
    blind?: boolean
    segment_mode?: 'whole' | 'sentence'
  }): Promise<any> => {
    const response = await api.post('/voice-city/auditions/compare', payload)
    return response.data
  },

  listPresets: async (): Promise<VoiceCityPreset[]> => {
    const response = await api.get<VoiceCityPreset[]>('/voice-city/presets')
    return response.data
  },

  createPreset: async (payload: {
    name: string
    description?: string
    category?: string
    parameters: VoiceParameters
    source_voice_version_id?: string
  }): Promise<VoiceCityPreset> => {
    const response = await api.post<VoiceCityPreset>('/voice-city/presets', payload)
    return response.data
  },

  listPronunciations: async (voiceId?: string): Promise<PronunciationRule[]> => {
    const response = await api.get<PronunciationRule[]>('/voice-city/pronunciations', { params: { voice_id: voiceId } })
    return response.data
  },

  createPronunciation: async (payload: PronunciationRule & { voice_id?: string | null }): Promise<PronunciationRule> => {
    const response = await api.post<PronunciationRule>('/voice-city/pronunciations', payload)
    return response.data
  },

  updatePronunciation: async (ruleId: string, payload: Partial<PronunciationRule>): Promise<PronunciationRule> => {
    const response = await api.patch<PronunciationRule>(`/voice-city/pronunciations/${ruleId}`, payload)
    return response.data
  },

  deletePronunciation: async (ruleId: string): Promise<void> => {
    await api.delete(`/voice-city/pronunciations/${ruleId}`)
  },

  listAutomation: async (voiceId: string): Promise<AutomationTrack[]> => {
    const response = await api.get<AutomationTrack[]>(`/voice-city/voices/${voiceId}/automation`)
    return response.data
  },

  createAutomation: async (voiceId: string, payload: Omit<AutomationTrack, 'id' | 'voice_id' | 'project_id'> & { project_id?: string | null }): Promise<AutomationTrack> => {
    const response = await api.post<AutomationTrack>(`/voice-city/voices/${voiceId}/automation`, payload)
    return response.data
  },

  updateAutomation: async (trackId: string, payload: Partial<AutomationTrack>): Promise<AutomationTrack> => {
    const response = await api.patch<AutomationTrack>(`/voice-city/automation/${trackId}`, payload)
    return response.data
  },

  deleteAutomation: async (trackId: string): Promise<void> => {
    await api.delete(`/voice-city/automation/${trackId}`)
  },

  qualityHistory: async (versionId: string): Promise<any[]> => {
    const response = await api.get(`/voice-city/versions/${versionId}/quality`)
    return response.data
  },

  recordQuality: async (versionId: string, payload: {
    metrics: QualityMetrics
    duration_tested_s: number
    notes?: string
  }): Promise<any> => {
    const response = await api.post(`/voice-city/versions/${versionId}/quality`, payload)
    return response.data
  },

  auditLog: async (voiceId?: string): Promise<any[]> => {
    const response = await api.get('/voice-city/audit', { params: { voice_id: voiceId } })
    return response.data
  },
}
