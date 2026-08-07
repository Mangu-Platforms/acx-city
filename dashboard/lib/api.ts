// Typed API client — all shapes match the real backend response structs in app.py

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? '').replace(/\/$/, '')

export const TOKEN_KEY = 'acx_dash_token'

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string | null) {
  if (typeof window === 'undefined') return
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body?.error ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

// ── Types (matching _job_json / health_check / usage in app.py) ─────────────

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'needs_review' | 'failed' | 'canceled'

export interface QCResult {
  duration_s: number | null
  loudness_dbfs: number | null
  peak_dbfs: number | null
  silence_ratio: number | null
  clipping: boolean
  issues: string[]
  passed: boolean
}

export interface Chapter {
  index: number
  title: string
  status: string
  cached_chunks: number
  total_chunks: number
  qc: QCResult | null
}

export interface Job {
  job_id: string
  task_id: string
  project_id: string
  status: JobStatus
  progress: number
  provider: string
  chapters_count: number
  current_chapter: number
  chapters: Chapter[]
  cached_chunks: number
  synthesized_chunks: number
  formats: string[]
  qc_issues: { chapter: string; issues: string[] }[]
  attempts: number
  error: string | null
}

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  service: string
  database: 'ok' | 'unreachable'
  providers: { name: string; display_name: string; available: boolean; paid: boolean }[]
}

export interface UsageResponse {
  period: string
  characters: number
  cost_usd: number
  quota: number | null
  remaining: number | null
}

export interface CacheStats {
  entries: number
  bytes: number
}

export interface AuthResponse {
  token: string
  user: { id: string; email: string; display_name?: string }
  organization?: { id: string; name: string }
}

// ── VoxEngine pipeline (served by the FastAPI sidecar under /v1) ─────────────

export interface PipelineTrace {
  chapter_number: number
  status: string
  current_agent: string | null
  agent1_ms: number | null
  agent2_ms: number | null
  agent3_ms: number | null
  agent4_ms: number | null
  agent5_ms: number | null
  qa_passed: boolean | null
  qa_completeness_score: number | null
  error: string | null
}

export interface PipelineStatus {
  job_id: string
  status: string
  chapters_total: number
  chapters_completed: number
  chapters_failed: number
  total_cost_usd: number
  traces: PipelineTrace[]
}

// ── API calls ────────────────────────────────────────────────────────────────

export const api = {
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const data = await req<AuthResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    setToken(data.token)
    return data
  },

  me: () => req<AuthResponse>('/api/auth/me'),

  health: () => req<HealthResponse>('/api/health'),

  jobs: () => req<Job[]>('/api/jobs'),

  job: (id: string) => req<Job>(`/api/jobs/${id}`),

  cancelJob: (id: string) =>
    req<{ job_id: string; status: string }>(`/api/jobs/${id}/cancel`, { method: 'POST' }),

  approveJob: (id: string) =>
    req<{ job_id: string; status: string }>(`/api/jobs/${id}/approve`, { method: 'POST' }),

  rejectJob: (id: string, reason: string) =>
    req<{ job_id: string; status: string }>(`/api/jobs/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  deleteJob: (id: string) =>
    req<{ deleted: boolean }>(`/api/jobs/${id}`, { method: 'DELETE' }),

  usage: () => req<UsageResponse>('/api/usage'),

  cacheStats: () => req<CacheStats>('/api/cache/stats'),

  pipelineStatus: (projectId: string) =>
    req<PipelineStatus>(`/v1/projects/${projectId}/pipeline/status`),
}
