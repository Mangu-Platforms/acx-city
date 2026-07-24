import axios from 'axios'
import { Provider, Voice, TaskStatus, SynthesisRequest, UploadResponse } from '../types'
import { synthesisRequestSchema, signedUrlSchema } from '../lib/schemas'

// Blueprint "repository rescue": the deployment must never call the visitor's
// own localhost. Resolve the API base from a validated env var, and fall back
// to a same-origin "/api" path (works behind a reverse proxy) instead of a
// hardcoded host.
function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (configured && configured.trim()) {
    return configured.trim().replace(/\/+$/, '')
  }
  // Same-origin default. In dev, Vite proxies /api to the backend (see vite.config.ts).
  return '/api'
}

const API_BASE_URL = resolveApiBase()

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' }
})

// --- Auth token handling ----------------------------------------------------
// The API is now authenticated; attach the bearer token to every request.
const TOKEN_KEY = 'audiobook_token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore storage errors */
  }
}

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface AuthResponse {
  token: string
  user: { id: string; email: string; display_name?: string }
  organization?: { id: string; name: string }
}

export const audiobookAPI = {
  signup: async (email: string, password: string, displayName?: string): Promise<AuthResponse> => {
    const res = await api.post<AuthResponse>('/auth/signup', { email, password, display_name: displayName })
    setToken(res.data.token)
    return res.data
  },
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const res = await api.post<AuthResponse>('/auth/login', { email, password })
    setToken(res.data.token)
    return res.data
  },
  logout: (): void => setToken(null),
  me: async (): Promise<AuthResponse> => {
    const res = await api.get<AuthResponse>('/auth/me')
    return res.data
  },
  listJobs: async (): Promise<TaskStatus[]> => {
    const res = await api.get<TaskStatus[]>('/jobs')
    return res.data
  },
  cancelJob: async (jobId: string): Promise<{ status: string }> => {
    const res = await api.post(`/jobs/${jobId}/cancel`)
    return res.data
  },
  getProviders: async (): Promise<Provider[]> => {
    const res = await api.get<Provider[]>('/providers')
    return res.data
  },
  getVoices: async (provider?: string, language?: string): Promise<Voice[]> => {
    const res = await api.get<Voice[]>('/voices', { params: { provider, language } })
    return res.data
  },
  synthesize: async (request: SynthesisRequest): Promise<{ task_id: string; status: string }> => {
    // Validate at the boundary before sending (throws a ZodError on bad input).
    const payload = synthesisRequestSchema.parse(request)
    const res = await api.post('/synthesize', payload)
    return res.data
  },
  uploadFile: async (file: File): Promise<UploadResponse> => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await api.post<UploadResponse>('/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    return res.data
  },
  getTaskStatus: async (taskId: string): Promise<TaskStatus> => {
    const res = await api.get<TaskStatus>(`/task/${taskId}`)
    return res.data
  },
  // Returns a time-limited signed URL to the audio in object storage. The
  // client follows this URL directly (bytes are no longer streamed through the
  // API), so downloads are scoped and links expire.
  getDownloadUrl: async (taskId: string, format: string = 'mp3'): Promise<string> => {
    const res = await api.get(`/download/${taskId}`, { params: { format } })
    return signedUrlSchema.parse(res.data).url
  },
  healthCheck: async (): Promise<{ status: string }> => {
    const res = await api.get('/health')
    return res.data
  }
}
