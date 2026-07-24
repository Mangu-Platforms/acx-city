export interface Provider {
  name: string
  display_name: string
  available: boolean
  paid: boolean
  max_chars: number
}

export interface Voice {
  id: string
  name: string
  language: string
  gender: string
  neural: boolean
}

export interface ChapterQC {
  duration_s: number
  loudness_dbfs: number | null
  peak_dbfs: number | null
  silence_ratio: number
  clipping: boolean
  issues: string[]
  passed: boolean
}

export interface ChapterState {
  title: string
  status: 'pending' | 'processing' | 'done' | 'skipped'
  cached_chunks: number
  total_chunks: number
  qc: ChapterQC | null
}

export interface TaskStatus {
  task_id: string
  status: 'started' | 'processing' | 'completed' | 'failed'
  progress: number
  provider?: string
  chapters_count: number
  current_chapter: number
  chapters?: ChapterState[]
  cached_chunks?: number
  synthesized_chunks?: number
  formats?: string[]
  qc_issues?: { chapter: string; issues: string[] }[]
  error?: string
}

export interface SynthesisRequest {
  text: string
  provider: string
  voice_id: string
  engine: 'neural' | 'standard'
  formats: string[]
  title?: string
  author?: string
}

export interface UploadResponse {
  text: string
  characters_count: number
  words_count: number
  detected_chapters?: string[]
}
