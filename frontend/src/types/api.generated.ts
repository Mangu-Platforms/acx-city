// AUTO-GENERATED — do not edit by hand.
// Source: backend/api/contracts/  |  Generator: backend/scripts/gen_ts_types.py
// Regenerate: cd backend && python scripts/gen_ts_types.py


export interface ErrorOut {
  error: string;
}

export interface CharacterVoiceOut {
  id: string;
  character_name: string;
  voice_id: string | null;
  voice_slug: string | null;
  pitch_adjustment: number;
  speed_adjustment: number;
  base_emotion: string;
  is_narrator: boolean;
  attribution_confidence: number | null;
  notes: string | null;
}

export interface SetCharacterIn {
  character_name: string;
  voice_id?: string | null;
  voice_slug?: string | null;
  pitch_adjustment?: number;
  speed_adjustment?: number;
  base_emotion?: string;
  is_narrator?: boolean;
  notes?: string | null;
}

export interface SetCharacterOut {
  id: string;
  updated?: boolean | null;
  created?: boolean | null;
}

export interface LexiconEntryOut {
  id: string;
  word: string;
  ipa_phoneme: string | null;
  phonetic_spelling: string | null;
  context_note: string | null;
  source: string;
  is_global: boolean;
}

export interface AddLexiconIn {
  word: string;
  ipa_phoneme?: string | null;
  phonetic_spelling?: string | null;
  context_note?: string | null;
  is_global?: boolean;
}

export interface AddLexiconOut {
  id: string;
  updated?: boolean | null;
  created?: boolean | null;
}

export interface DeleteOut {
  deleted: boolean;
}

export interface PipelineTraceOut {
  chapter_number: number;
  status: string;
  current_agent: string | null;
  agent1_ms: number | null;
  agent2_ms: number | null;
  agent3_ms: number | null;
  agent4_ms: number | null;
  agent5_ms: number | null;
  qa_passed: boolean | null;
  qa_completeness_score: number | null;
  error: string | null;
}

export interface PipelineStatusOut {
  job_id: string;
  status: string;
  chapters_total: number;
  chapters_completed: number;
  chapters_failed: number;
  total_cost_usd: number;
  traces: PipelineTraceOut[];
}

export interface PipelineTraceDetailOut {
  id: string;
  job_id: string;
  chapter_number: number;
  status: string;
  current_agent: string | null;
  agents: Record<string, unknown>;
  characters_in: unknown | null;
  characters_out: unknown | null;
  qa_passed: boolean | null;
  qa_issues: unknown | null;
  qa_completeness_score: number | null;
  error: string | null;
}

export interface AgentTimingOut {
  ms: number | null;
  cost_usd?: number | null;
}

export interface PipelineStartOut {
  error: string;
}

export interface StockVoiceOut {
  id: string;
  slug: string;
  display_name: string;
  gender: string;
  accent: string;
  age_range?: string | null;
  style_tags: string[];
  description?: string | null;
  provider: string;
  provider_voice_id?: string | null;
  sample_audio_url?: string | null;
  languages: string[];
  emotion_tags: string[];
  is_active: boolean;
  is_cloneable: boolean;
  source: string;
  has_latent_embedding: boolean;
  created_at?: string | null;
}

export interface ListVoicesOut {
  voices: StockVoiceOut[];
  total: number;
  page: number;
  pages: number;
}

export interface VoiceDetailOut {
  id: string;
  slug: string;
  display_name: string;
  gender: string;
  accent: string;
  age_range?: string | null;
  style_tags: string[];
  description?: string | null;
  provider: string;
  provider_voice_id?: string | null;
  sample_audio_url?: string | null;
  languages: string[];
  emotion_tags: string[];
  is_active: boolean;
  is_cloneable: boolean;
  source: string;
  has_latent_embedding: boolean;
  created_at?: string | null;
  latent_s3_key?: string | null;
  organization_id?: string | null;
  voice_city_voice_id?: string | null;
}

export interface VoiceCloneOut {
  id: string;
  name: string;
  status: string;
  provider: string;
  reference_duration_seconds?: number | null;
  safety_similarity_score?: number | null;
  error?: string | null;
  created_at?: string | null;
}

export interface ListClonesOut {
  clones: VoiceCloneOut[];
  total: number;
}

export interface CreateCloneOut {
  clone_id: string;
  name: string;
  status: string;
  message: string;
}

export interface PreviewOut {
  preview_url: string;
  expires_in: number;
  voice_id: string;
}

export interface RerenderOut {
  error: string;
}

export interface WaveformOut {
  chapter_id: string;
  duration_s: number | null;
  sample_rate: number;
  peaks: unknown[];
  markers: unknown[];
}
