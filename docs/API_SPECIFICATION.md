# ACX City — API Specification

> **Version:** 1.0.0  
> **Last Updated:** 2026-08-07  
> **Base URLs:**
> - Flask API: `https://<host>/api/*`
> - FastAPI sidecar: `https://<host>/v1/*`
> - MCP Server: `https://<host>:8765` (streamable HTTP)

---

## Table of Contents

- [1. Authentication & Authorization](#1-authentication--authorization)
- [2. Flask API (`/api/*`)](#2-flask-api-api)
  - [2.1 Auth](#21-auth)
  - [2.2 Discovery](#22-discovery)
  - [2.3 Upload & Text Processing](#23-upload--text-processing)
  - [2.4 Synthesis & Jobs](#24-synthesis--jobs)
  - [2.5 Downloads](#25-downloads)
  - [2.6 Usage & Billing](#26-usage--billing)
  - [2.7 Health & Metrics](#27-health--metrics)
  - [2.8 EPUB Export](#28-epub-export)
  - [2.9 Streaming](#29-streaming)
  - [2.10 Webhooks](#210-webhooks)
  - [2.11 Voice City](#211-voice-city)
- [3. FastAPI (`/v1/*`)](#3-fastapi-v1)
  - [3.1 Pipeline](#31-pipeline)
  - [3.2 Characters](#32-characters)
  - [3.3 Lexicon](#33-lexicon)
  - [3.4 Voices](#34-voices)
  - [3.5 Clones](#35-clones)
  - [3.6 Chapters](#36-chapters)
  - [3.7 Health](#37-health)
- [4. MCP Tools](#4-mcp-tools)
- [5. Common Schemas](#5-common-schemas)
- [6. Error Handling](#6-error-handling)
- [7. Rate Limiting & Quotas](#7-rate-limiting--quotas)

---

## 1. Authentication & Authorization

### Auth Scheme

All authenticated endpoints require a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are issued by `/api/auth/signup` and `/api/auth/login`.

### Multi-Tenancy

All resources are **organization-scoped**. A user belongs to an organization via a `Membership` record. Job access is authorized by walking the `User → Membership → Organization → Job` ownership chain — possessing a task/job ID alone does not grant access.

### Role Model

| Role | Description |
|------|-------------|
| `owner` | Full org control |
| `admin` | Administrative access |
| `member` | Standard access |

### MCP Authentication

The MCP server uses a separate **API key** (`MCP_API_KEY` env var). Clients must send:

```
Authorization: Bearer <MCP_API_KEY>
```

---

## 2. Flask API (`/api/*`)

### 2.1 Auth

#### POST `/api/auth/signup`

Create a new user and organization, returns a JWT token.

**Auth Required:** No

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "display_name": "Jane Doe",
  "org_name": "My Studio"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | ✅ | User email (must be unique) |
| `password` | string | ✅ | Password (minimum length enforced) |
| `display_name` | string | ❌ | User's display name |
| `org_name` | string | ❌ | Organization name |

**Response (201):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "Jane Doe"
  },
  "organization": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "My Studio"
  }
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | Email already registered, invalid email, or weak password |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass123","display_name":"Jane","org_name":"Studio"}'
```

---

#### POST `/api/auth/login`

Authenticate and receive a token.

**Auth Required:** No

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com"
  }
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `401` | Invalid credentials |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass123"}'
```

---

#### GET `/api/auth/me`

Get the current authenticated user and organization details.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "Jane Doe"
  },
  "organization": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "My Studio"
  },
  "role": "owner"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |

**Example:**
```bash
curl https://api.acxcity.com/api/auth/me \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### 2.2 Discovery

#### GET `/api/providers`

List all available TTS providers with availability and pricing info.

**Auth Required:** No

**Response (200):**
```json
[
  {
    "name": "edge",
    "available": true,
    "paid": false,
    "voices_count": 300
  },
  {
    "name": "polly",
    "available": true,
    "paid": true,
    "voices_count": 50
  }
]
```

**Example:**
```bash
curl https://api.acxcity.com/api/providers
```

---

#### GET `/api/voices`

List voices for a specific TTS provider.

**Auth Required:** No

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | system default | Provider name (e.g., `edge`, `polly`) |
| `language` | string | — | Filter by language code |

**Response (200):**
```json
[
  {
    "id": "en-US-AriaNeural",
    "name": "Aria",
    "language": "en-US",
    "gender": "Female"
  }
]
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | Unknown provider name |

**Example:**
```bash
curl "https://api.acxcity.com/api/voices?provider=edge&language=en"
```

---

### 2.3 Upload & Text Processing

#### POST `/api/upload`

Upload a manuscript file (`.txt`, `.pdf`, `.docx`) for text extraction and chapter detection.

**Auth Required:** ✅ Bearer token

**Content-Type:** `multipart/form-data`

**Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | ✅ | The manuscript file |

**Allowed Extensions:** `.txt`, `.pdf`, `.docx`  
**Max File Size:** 100 MB

**Response (200):**
```json
{
  "text": "Full extracted text content...",
  "characters_count": 125000,
  "words_count": 21000,
  "detected_chapters": [
    "Chapter 1: The Beginning",
    "Chapter 2: The Journey",
    "Chapter 3: The End"
  ]
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | No file provided or empty filename |
| `415` | Unsupported file type or MIME type |
| `500` | File save failure |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/upload \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -F "file=@manuscript.pdf"
```

---

### 2.4 Synthesis & Jobs

#### POST `/api/synthesize`

Create a project and enqueue a durable synthesis job. The job is processed asynchronously by a separate worker process.

**Auth Required:** ✅ Bearer token

**Request Body:**
```json
{
  "text": "Full manuscript text to synthesize...",
  "title": "My Audiobook",
  "author": "Author Name",
  "provider": "edge",
  "voice_id": "en-US-AriaNeural",
  "voice_version_id": "uuid-of-voice-version",
  "engine": "neural",
  "formats": ["mp3", "m4b"],
  "voice_overrides": {},
  "voice_direction": {}
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | ✅ | — | Source text to synthesize |
| `title` | string | ❌ | `"Untitled"` | Project title |
| `author` | string | ❌ | `null` | Author name |
| `provider` | string | ❌ | system default | TTS provider name |
| `voice_id` | string | ❌ | first available | Provider voice ID |
| `voice_version_id` | string | ❌ | — | Voice City immutable version ID (required for voice-city provider) |
| `engine` | string | ❌ | `"neural"` | TTS engine type |
| `formats` | string[] | ❌ | `["mp3","m4b"]` | Output formats |
| `voice_overrides` | object | ❌ | `{}` | Performance overrides for Voice City |
| `voice_direction` | object | ❌ | `{}` | Direction plan for Voice City |

**Response (201):**
```json
{
  "task_id": "770e8400-e29b-41d4-a716-446655440002",
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "queued"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | No text, unknown provider, voice-city requires `voice_version_id` |
| `402` | Monthly usage quota exceeded |
| `429` | Rate limit exceeded (includes `Retry-After` header) |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/synthesize \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Chapter 1\n\nIt was a dark and stormy night...",
    "title": "My Book",
    "provider": "edge",
    "voice_id": "en-US-AriaNeural"
  }'
```

---

#### GET `/api/jobs`

List all jobs for the current organization, newest first.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
[
  {
    "task_id": "770e8400-...",
    "job_id": "770e8400-...",
    "project_id": "880e8400-...",
    "status": "running",
    "progress": 45,
    "provider": "edge",
    "voice_version_id": "uuid",
    "voice_display_name": "Aria V2",
    "voice_parameter_fingerprint": "abc123",
    "chapters_count": 12,
    "current_chapter": 5,
    "chapters": [...],
    "cached_chunks": 150,
    "synthesized_chunks": 300,
    "formats": ["mp3", "m4b"],
    "qc_issues": [],
    "attempts": 1,
    "error": null
  }
]
```

**Example:**
```bash
curl https://api.acxcity.com/api/jobs \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

#### GET `/api/jobs/:id`

Get detailed status of a specific job including per-chapter progress and QC results.

**Auth Required:** ✅ Bearer token (must own the job's organization)

**Response (200):**

Same schema as individual items in `/api/jobs` list, plus full chapter details:

```json
{
  "task_id": "770e8400-...",
  "job_id": "770e8400-...",
  "status": "running",
  "progress": 45,
  "chapters": [
    {
      "index": 0,
      "title": "Chapter 1",
      "status": "done",
      "cached_chunks": 15,
      "total_chunks": 15,
      "qc": {
        "duration_s": 320.5,
        "loudness_dbfs": -18.2,
        "peak_dbfs": -3.1,
        "silence_ratio": 0.08,
        "clipping": false,
        "issues": [],
        "passed": true
      }
    }
  ]
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or not owned by caller's org |

**Example:**
```bash
curl https://api.acxcity.com/api/jobs/770e8400-... \
  -H "Authorization: Bearer eyJhbGciOi..."
```

> **Note:** Also available via legacy route `GET /api/task/:id`.

---

#### POST `/api/jobs/:id/cancel`

Cancel a running or queued synthesis job.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "status": "canceled",
  "cancel_requested": true
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or access denied |
| `409` | Job already in terminal state (`succeeded`, `failed`, `canceled`) |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/jobs/770e8400-.../cancel \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

#### POST `/api/jobs/:id/approve`

Approve a job held in `needs_review` status (QC gate). Transitions to `succeeded`.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "status": "succeeded"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or access denied |
| `409` | Job not in `needs_review` status |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/jobs/770e8400-.../approve \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

#### POST `/api/jobs/:id/reject`

Reject a reviewed job. Transitions from `needs_review` to `failed`.

**Auth Required:** ✅ Bearer token

**Request Body (optional):**
```json
{
  "reason": "Audio quality below threshold"
}
```

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "status": "failed"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or access denied |
| `409` | Job not in `needs_review` status |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/jobs/770e8400-.../reject \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -H "Content-Type: application/json" \
  -d '{"reason": "Quality issues"}'
```

---

#### DELETE `/api/jobs/:id`

Delete a job and all its stored audio assets. The job row and associated storage objects are permanently removed.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "deleted": true,
  "assets_removed": 5
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or access denied |

**Example:**
```bash
curl -X DELETE https://api.acxcity.com/api/jobs/770e8400-... \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### 2.5 Downloads

#### GET `/api/download/:id`

Get a time-limited signed URL for downloading the completed audiobook. Also available at `GET /api/jobs/:id/download`.

**Auth Required:** ✅ Bearer token

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | string | `"mp3"` | Output format (`mp3` or `m4b`) |
| `redirect` | string | — | Set to `"1"` to 302-redirect to the signed URL |

**Response (200):**
```json
{
  "url": "https://storage.example.com/...",
  "expires_in": 3600
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `403` | Job not found or access denied |
| `404` | No output available for requested format |
| `409` | Job not in `succeeded` or `needs_review` status |

**Example:**
```bash
curl "https://api.acxcity.com/api/download/770e8400-...?format=mp3" \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

#### GET `/api/files/:key`

Serve a local-storage object via a valid signed URL. Used only by the `LocalStorage` backend (cloud backends sign URLs pointing directly at the object store).

**Auth Required:** No (the HMAC signature IS the authorization)

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `expires` | int | ✅ | Expiration timestamp (epoch seconds) |
| `sig` | string | ✅ | HMAC signature |
| `name` | string | ❌ | Download filename override |

**Response (200):** Binary audio file (`audio/mpeg` or `audio/mp4`)

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | Invalid `expires` parameter |
| `403` | Invalid or expired signature |
| `404` | File not found or not using local storage |

**Example:**
```bash
curl "https://api.acxcity.com/api/files/jobs/abc/output.mp3?expires=1691000000&sig=hmac123"
```

---

### 2.6 Usage & Billing

#### GET `/api/usage`

Get the current organization's month-to-date synthesis usage and remaining quota.

**Auth Required:** ✅ Bearer token

**Response (200):**
```json
{
  "period": "2026-08",
  "characters": 1250000,
  "cost_usd": 12.50,
  "quota": 5000000,
  "remaining": 3750000
}
```

> `quota` is `null` for unlimited plans. `remaining` is `null` when quota is unlimited.

**Example:**
```bash
curl https://api.acxcity.com/api/usage \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### 2.7 Health & Metrics

#### GET `/api/health`

Platform health check. Reports database reachability and TTS provider availability.

**Auth Required:** No

**Response (200 or 503):**
```json
{
  "status": "healthy",
  "service": "Audiobook Production API",
  "database": "ok",
  "providers": [
    {"name": "edge", "available": true, "paid": false},
    {"name": "polly", "available": true, "paid": true}
  ]
}
```

| HTTP Code | `status` | Meaning |
|-----------|----------|---------|
| `200` | `"healthy"` | All systems operational |
| `503` | `"degraded"` | Database unreachable |

**Example:**
```bash
curl https://api.acxcity.com/api/health
```

---

#### GET `/api/metrics`

Prometheus-compatible metrics endpoint. Returns platform metrics in plain text exposition format.

**Auth Required:** No

**Response (200):** `text/plain; charset=utf-8`

```
# HELP acx_jobs_total Total jobs by status
# TYPE acx_jobs_total gauge
acx_jobs_total{status="queued"} 5
acx_jobs_total{status="running"} 2
acx_jobs_total{status="succeeded"} 120
acx_jobs_total{status="failed"} 3
# HELP acx_organizations_total Total organizations
# TYPE acx_organizations_total gauge
acx_organizations_total 15
# HELP acx_characters_used_current_month Characters used this month
# TYPE acx_characters_used_current_month gauge
acx_characters_used_current_month 2500000
# HELP acx_cost_usd_current_month Cost in USD this month
# TYPE acx_cost_usd_current_month gauge
acx_cost_usd_current_month 25.00
```

**Errors:**
| Code | Condition |
|------|-----------|
| `500` | Internal error (returns `# ERROR: ...` in plain text) |

**Example:**
```bash
curl https://api.acxcity.com/api/metrics
```

---

### 2.8 EPUB Export

#### POST `/api/export/epub`

Generate an EPUB file from provided chapter data.

**Auth Required:** ✅ Bearer token

**Request Body:**
```json
{
  "title": "My Book Title",
  "author": "Author Name",
  "chapters": [
    {
      "title": "Chapter 1: The Beginning",
      "content": "It was a dark and stormy night..."
    },
    {
      "title": "Chapter 2: The Journey",
      "content": "The next morning, they set out..."
    }
  ]
}
```

**Response (200):**
```json
{
  "success": true,
  "size": 45678,
  "storage_key": "epub/org-uuid/abc123.epub"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | No chapters provided |
| `500` | EPUB generation failure |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/export/epub \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Book",
    "author": "Jane Doe",
    "chapters": [{"title": "Ch 1", "content": "Hello world"}]
  }'
```

---

#### GET `/api/jobs/:id/export/epub`

Export a completed synthesis job as an EPUB file. Uses the job's chapter data.

**Auth Required:** ✅ Bearer token

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `redirect` | string | — | Set to `"1"` to 302-redirect to the signed URL |

**Response (200):**
```json
{
  "success": true,
  "url": "https://storage.example.com/...",
  "expires_in": 3600,
  "size": 45678
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | Missing project metadata |
| `403` | Job not found or access denied |
| `404` | No chapter content available |
| `409` | Job not in `succeeded` status |

**Example:**
```bash
curl "https://api.acxcity.com/api/jobs/770e8400-.../export/epub" \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### 2.9 Streaming

> Streaming endpoints are served by the `streaming` blueprint mounted at `/api/stream`.

#### GET `/api/stream/:jobId/chapter/:chapter`

Stream a completed chapter's audio with HTTP Range support for seekable playback.

**Auth Required:** ✅ Bearer token

**Response (200):** `audio/mpeg` — Chunked MP3 stream

**Headers:**
- `Accept-Ranges: bytes` — indicates Range request support
- `Content-Disposition: inline; filename="chapter_001.mp3"`

**Range Requests:**

Send `Range: bytes=<start>-` header to seek. Response `206 Partial Content` with:
- `Content-Range: bytes <start>-<end>/<total>`
- `Content-Length: <chunk size>`

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Job/chapter not found, or audio file not available |
| `409` | Job not completed or chapter not ready |
| `416` | Invalid Range header |

**Example:**
```bash
curl https://api.acxcity.com/api/stream/770e8400-.../chapter/1 \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

#### POST `/api/stream/preview`

Stream an instant voice preview. The text is synthesized on-the-fly and streamed as chunked MP3.

**Auth Required:** ✅ Bearer token

**Request Body:**
```json
{
  "text": "Hello, welcome to the show.",
  "voice_id": "en-US-AriaNeural",
  "emotion": "excited",
  "duration": 5.0
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | ✅ | — | Text to synthesize (max 2000 chars) |
| `voice_id` | string | ✅ | — | Provider voice identifier |
| `emotion` | string | ❌ | — | Emotion/style tag |
| `duration` | float | ❌ | `5.0` | Target duration in seconds |

**Response (200):** `audio/mpeg` — Chunked stream, `Transfer-Encoding: chunked`

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | Missing `text` or `voice_id`, text too long |
| `500` | Preview synthesis failure |
| `503` | No speech provider available |

**Example:**
```bash
curl -X POST https://api.acxcity.com/api/stream/preview \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","voice_id":"en-US-AriaNeural","emotion":"happy"}' \
  --output preview.mp3
```

---

### 2.10 Webhooks

#### POST `/api/webhooks/github`

GitHub webhook receiver for repository integration events.

**Auth Required:** GitHub webhook signature verification

**Content-Type:** `application/json`

---

### 2.11 Voice City

> All Voice City endpoints are under `/api/voice-city/*` and require authentication.

#### Discovery & Configuration

##### GET `/api/voice-city/capabilities`

Get Voice City capabilities for the current organization.

**Auth Required:** ✅

**Example:**
```bash
curl https://api.acxcity.com/api/voice-city/capabilities \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

##### GET `/api/voice-city/schema`

Get the Voice City parameter schema document.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"laboratory"` | Schema mode |
| `search` | string | — | Filter schema by search term |

---

##### GET `/api/voice-city/audition-scripts`

Get audition scripts for voice testing.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `category` | string | Filter by script category |

---

#### Direction & Analysis

##### POST `/api/voice-city/direction/analyze`

Analyze manuscript text for character dialogue and direction cues.

**Auth Required:** ✅

**Request Body:**
```json
{
  "text": "\"Hello,\" said John angrily. \"I'm fine,\" she replied softly."
}
```

---

##### POST `/api/voice-city/direction/validate`

Validate a voice direction plan.

**Auth Required:** ✅

**Request Body:**
```json
{
  "plan": { ... },
  "seed": 481928
}
```

---

#### Voices CRUD

##### GET `/api/voice-city/voices`

List voices for the current organization.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter by voice status |

---

##### POST `/api/voice-city/voices`

Create a new voice.

**Auth Required:** ✅

**Request Body:**
```json
{
  "name": "Narrator Alpha",
  "description": "A warm, deep male narrator",
  "parameters": { ... },
  "seed": 481928,
  "provider": "edge",
  "provider_voice_id": "en-US-GuyNeural",
  "tags": ["narrator", "warm"],
  "default_use_cases": ["fiction", "non-fiction"]
}
```

**Response:** `201 Created`

---

##### GET `/api/voice-city/voices/:voice_id`

Get a single voice with all details.

**Auth Required:** ✅

---

##### PATCH `/api/voice-city/voices/:voice_id`

Update voice metadata.

**Auth Required:** ✅

**Request Body:**
```json
{
  "name": "Updated Name",
  "description": "Updated description",
  "tags": ["updated"],
  "default_use_cases": ["fiction"],
  "visibility": "private"
}
```

---

##### DELETE `/api/voice-city/voices/:voice_id`

Delete a voice.

**Auth Required:** ✅

**Response:**
```json
{"voice_id": "uuid", "deleted": true}
```

---

#### Voice Versions

##### POST `/api/voice-city/voices/:voice_id/versions`

Save a new version of a voice.

**Auth Required:** ✅

**Request Body:**
```json
{
  "parameters": { ... },
  "change_note": "Adjusted pitch",
  "provider_voice_id": "en-US-GuyNeural",
  "expected_current_version_id": "uuid"
}
```

**Response:** `201 Created`

---

##### POST `/api/voice-city/voices/:voice_id/rollback`

Rollback a voice to a previous version.

**Auth Required:** ✅

**Request Body:**
```json
{
  "version_id": "uuid-of-target-version"
}
```

---

##### POST `/api/voice-city/voices/:voice_id/revoke`

Revoke a voice (soft-delete with reason).

**Auth Required:** ✅

**Request Body:**
```json
{
  "reason": "No longer needed"
}
```

---

##### GET `/api/voice-city/voices/:voice_id/export`

Export a voice recipe (JSON).

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `version_id` | string | Specific version to export |

---

#### Generation

##### POST `/api/voice-city/generate`

Generate voice variants from a description.

**Auth Required:** ✅

**Request Body:**
```json
{
  "description": "A warm, middle-aged female narrator with a slight British accent",
  "provider": "edge",
  "count": 4,
  "seed": 481928,
  "locked_paths": []
}
```

**Response:** `201 Created`

---

##### POST `/api/voice-city/versions/:version_id/mutate`

Mutate a voice version based on a text request.

**Auth Required:** ✅

**Request Body:**
```json
{
  "request": "Make it deeper and slower",
  "seed": 481928,
  "locked_paths": []
}
```

**Response:** `201 Created`

---

##### POST `/api/voice-city/versions/:version_id/optimize`

Optimize a voice version for production quality.

**Auth Required:** ✅

**Response:** `202 Accepted`

---

##### POST `/api/voice-city/breed`

Breed two voice versions together.

**Auth Required:** ✅

**Request Body:**
```json
{
  "version_a_id": "uuid",
  "version_b_id": "uuid",
  "weight_a": 0.7,
  "seed": 481928,
  "locked_from_a": []
}
```

**Response:** `201 Created`

---

#### Candidates

##### GET `/api/voice-city/candidate-sets/:candidate_set_id`

List candidates in a candidate set.

**Auth Required:** ✅

---

##### GET `/api/voice-city/candidates/:candidate_id`

Get a single candidate.

**Auth Required:** ✅

---

##### POST `/api/voice-city/candidates/compare`

Compare multiple candidates side-by-side.

**Auth Required:** ✅

**Request Body:**
```json
{
  "candidate_ids": ["uuid1", "uuid2", "uuid3"]
}
```

---

##### POST `/api/voice-city/candidates/:candidate_id/accept`

Accept a candidate (promote to a voice version).

**Auth Required:** ✅

**Request Body:**
```json
{
  "voice_id": "existing-voice-uuid",
  "name": "Version 3",
  "change_note": "Accepted from generation batch"
}
```

**Response:** `201 Created`

---

##### POST `/api/voice-city/candidates/:candidate_id/reject`

Reject a candidate.

**Auth Required:** ✅

**Request Body:**
```json
{
  "reason": "Doesn't match the intended tone"
}
```

---

#### Generation Jobs

##### GET `/api/voice-city/generation-jobs/:job_id`

Get status of a generation job.

**Auth Required:** ✅

---

##### POST `/api/voice-city/generation-jobs/:job_id/cancel`

Cancel a running generation job.

**Auth Required:** ✅

**Response:** `202 Accepted`

---

#### Audition Room (Previews)

##### POST `/api/voice-city/previews`

Render a voice preview audio clip.

**Auth Required:** ✅

**Request Body:**
```json
{
  "voice_version_id": "uuid",
  "candidate_id": "uuid",
  "text": "Hello, this is a test.",
  "script_id": "uuid",
  "overrides": {},
  "engine": "neural",
  "loudness_match": true
}
```

> Provide exactly one of `voice_version_id` or `candidate_id`.

**Response:** `201 Created`
```json
{
  "id": "preview-uuid",
  "status": "completed",
  "duration_s": 3.2,
  "display_name": "Aria V2"
}
```

---

##### GET `/api/voice-city/previews`

List previews for the current organization.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `voice_version_id` | string | Filter by voice version |

---

##### GET `/api/voice-city/previews/:preview_id/url`

Get a signed download URL for a preview audio file.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `expires_in` | int | `3600` | URL expiry in seconds |

**Response:**
```json
{
  "url": "https://storage.example.com/...",
  "expires_in": 3600
}
```

---

##### DELETE `/api/voice-city/previews/:preview_id`

Delete a preview and its stored audio.

**Auth Required:** ✅

**Response:**
```json
{"preview_id": "uuid", "deleted": true}
```

---

##### POST `/api/voice-city/auditions/compare`

Compare multiple voice versions/candidates with A/B or blind testing.

**Auth Required:** ✅

**Request Body:**
```json
{
  "sources": [
    {"voice_version_id": "uuid1"},
    {"voice_version_id": "uuid2", "overrides": {}}
  ],
  "text": "Sample comparison text.",
  "script_id": "uuid",
  "segment_mode": "sentence",
  "blind": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sources` | object[] | ✅ | 2-8 voice sources (each with `voice_version_id` or `candidate_id`) |
| `text` | string | ✅ | Comparison text |
| `script_id` | string | ❌ | Audition script ID |
| `segment_mode` | string | ❌ | `"whole"` (default) or `"sentence"` |
| `blind` | bool | ❌ | Enable blind A/B testing |

**Response:** `201 Created`
```json
{
  "comparison_id": "hash20",
  "blind": true,
  "segment_mode": "sentence",
  "sources": [
    {
      "source_index": 0,
      "blind_label": "Sample B",
      "previews": [
        {"segment_index": 0, "text": "...", "preview_id": "uuid", "duration_s": 2.1}
      ]
    }
  ],
  "reveal": [
    {"label": "Sample B", "display_name": "Aria V2"}
  ]
}
```

---

#### Presets

##### GET `/api/voice-city/presets`

List voice presets for the current organization.

**Auth Required:** ✅

---

##### POST `/api/voice-city/presets`

Create a voice preset.

**Auth Required:** ✅

**Request Body:**
```json
{
  "name": "Warm Narrator",
  "description": "Standard warm narration preset",
  "category": "custom",
  "parameters": { ... },
  "source_voice_version_id": "uuid"
}
```

**Response:** `201 Created`

---

##### GET `/api/voice-city/presets/:preset_id`

Resolve and get a preset.

**Auth Required:** ✅

---

##### DELETE `/api/voice-city/presets/:preset_id`

Delete a preset.

**Auth Required:** ✅

**Response:**
```json
{"preset_id": "uuid", "deleted": true}
```

---

#### Pronunciation Dictionary

##### GET `/api/voice-city/pronunciations`

List pronunciation rules.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `voice_id` | string | Filter by voice |

---

##### POST `/api/voice-city/pronunciations`

Create a pronunciation rule.

**Auth Required:** ✅

**Response:** `201 Created`

---

##### PATCH `/api/voice-city/pronunciations/:rule_id`

Update a pronunciation rule.

**Auth Required:** ✅

---

##### DELETE `/api/voice-city/pronunciations/:rule_id`

Delete a pronunciation rule.

**Auth Required:** ✅

**Response:**
```json
{"rule_id": "uuid", "deleted": true}
```

---

#### Automation Curves

##### GET `/api/voice-city/voices/:voice_id/automation`

List automation tracks for a voice.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `project_id` | string | Filter by project |

---

##### POST `/api/voice-city/voices/:voice_id/automation`

Create an automation track.

**Auth Required:** ✅

**Response:** `201 Created`

---

##### PATCH `/api/voice-city/automation/:track_id`

Update an automation track.

**Auth Required:** ✅

---

##### DELETE `/api/voice-city/automation/:track_id`

Delete an automation track.

**Auth Required:** ✅

**Response:**
```json
{"track_id": "uuid", "deleted": true}
```

---

#### Quality & Audit

##### GET `/api/voice-city/versions/:version_id/quality`

Get quality evaluation history for a voice version.

**Auth Required:** ✅

---

##### POST `/api/voice-city/versions/:version_id/quality`

Record a quality evaluation.

**Auth Required:** ✅

**Request Body:**
```json
{
  "metrics": { ... },
  "duration_tested_s": 120.0,
  "notes": "Good quality in quiet passages"
}
```

**Response:** `201 Created`

---

##### GET `/api/voice-city/audit`

Get the Voice City audit log.

**Auth Required:** ✅

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `voice_id` | string | — | Filter by voice |
| `limit` | int | `200` | Max entries |

---

##### POST `/api/voice-city/reference-authorizations`

Create a reference audio authorization record.

**Auth Required:** ✅

**Response:** `201 Created`

---

## 3. FastAPI (`/v1/*`)

> The FastAPI sidecar runs alongside Flask. NGINX routes `/v1/*` here and `/api/*` to Flask.
>
> **Base URL:** `https://<host>/v1/`  
> **OpenAPI spec:** `GET /v1/openapi.json`  
> **Swagger UI:** `GET /v1/docs`

### 3.1 Pipeline

#### POST `/v1/projects/:id/pipeline/start`

Kick off multi-agent preprocessing for all chapters in a project. Uses the 5-agent pipeline: Structure Parser → Character Attribution → Text Normalizer → Prosody Planner → QA Validator.

**Auth Required:** No (internal service-to-service)

**Request Body:**
```json
{
  "force": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `force` | bool | `false` | Re-process even if already processed |

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "task_id": "celery-task-id",
  "chapters_dispatched": 12,
  "status": "processing"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `400` | No active job found, or project has no source text |
| `404` | Project not found |
| `500` | Structure parsing failure |

**Example:**
```bash
curl -X POST https://api.acxcity.com/v1/projects/880e8400-.../pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

---

#### GET `/v1/projects/:id/pipeline/status`

Get per-chapter pipeline status and agent costs.

**Auth Required:** No

**Response (200):**
```json
{
  "job_id": "770e8400-...",
  "status": "running",
  "chapters_total": 12,
  "chapters_completed": 8,
  "chapters_failed": 0,
  "total_cost_usd": 0.0045,
  "traces": [
    {
      "chapter_number": 1,
      "status": "completed",
      "current_agent": null,
      "agent1_ms": 120,
      "agent2_ms": 340,
      "agent3_ms": 85,
      "agent4_ms": 200,
      "agent5_ms": 95,
      "qa_passed": true,
      "qa_completeness_score": 0.98,
      "error": null
    }
  ]
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Project or job not found |

**Example:**
```bash
curl https://api.acxcity.com/v1/projects/880e8400-.../pipeline/status
```

---

#### GET `/v1/projects/:id/pipeline/trace/:chapter`

Get the full agent trace for a specific chapter, including per-agent timing, cost, and QA results.

**Auth Required:** No

**Response (200):**
```json
{
  "id": "trace-uuid",
  "job_id": "770e8400-...",
  "chapter_number": 1,
  "status": "completed",
  "current_agent": null,
  "agents": {
    "structure_parser": {"ms": 120},
    "character_attribution": {"ms": 340, "cost_usd": 0.0012},
    "text_normalizer": {"ms": 85, "cost_usd": 0.0003},
    "prosody_planner": {"ms": 200, "cost_usd": 0.0008},
    "qa_validator": {"ms": 95, "cost_usd": 0.0}
  },
  "characters_in": 5200,
  "characters_out": 5150,
  "qa_passed": true,
  "qa_issues": null,
  "qa_completeness_score": 0.98,
  "error": null
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Project, job, or chapter trace not found |

**Example:**
```bash
curl https://api.acxcity.com/v1/projects/880e8400-.../pipeline/trace/1
```

---

### 3.2 Characters

#### GET `/v1/projects/:id/characters`

Get character voice assignments for a project.

**Auth Required:** No

**Response (200):**
```json
[
  {
    "id": "uuid",
    "character_name": "John",
    "voice_id": "en-US-GuyNeural",
    "voice_slug": "en-US-GuyNeural",
    "pitch_adjustment": 1.0,
    "speed_adjustment": 1.0,
    "base_emotion": "neutral",
    "is_narrator": false,
    "attribution_confidence": 0.95,
    "notes": null
  }
]
```

**Example:**
```bash
curl https://api.acxcity.com/v1/projects/880e8400-.../characters
```

---

#### POST `/v1/projects/:id/characters`

Set or update a character voice assignment. If a character with the same name exists, it is updated; otherwise, a new one is created.

**Auth Required:** No

**Request Body:**
```json
{
  "character_name": "John",
  "voice_id": "en-US-GuyNeural",
  "voice_slug": "en-US-GuyNeural",
  "pitch_adjustment": 1.05,
  "speed_adjustment": 0.95,
  "base_emotion": "neutral",
  "is_narrator": false,
  "notes": "Main character, deep voice"
}
```

**Response (200):**
```json
{"id": "uuid", "created": true}
```
or
```json
{"id": "uuid", "updated": true}
```

**Example:**
```bash
curl -X POST https://api.acxcity.com/v1/projects/880e8400-.../characters \
  -H "Content-Type: application/json" \
  -d '{"character_name":"John","voice_id":"en-US-GuyNeural","is_narrator":false}'
```

---

### 3.3 Lexicon

#### GET `/v1/projects/:id/lexicon`

Get pronunciation lexicon entries for a project.

**Auth Required:** No

**Response (200):**
```json
[
  {
    "id": "uuid",
    "word": "Hermione",
    "ipa_phoneme": "/hɜːrˈmaɪəni/",
    "phonetic_spelling": "her-MY-uh-nee",
    "context_note": "Character name from Harry Potter",
    "source": "manual",
    "is_global": false
  }
]
```

**Example:**
```bash
curl https://api.acxcity.com/v1/projects/880e8400-.../lexicon
```

---

#### POST `/v1/projects/:id/lexicon`

Add or update a pronunciation lexicon entry. If the word already exists for this project, it is updated.

**Auth Required:** No

**Request Body:**
```json
{
  "word": "Hermione",
  "ipa_phoneme": "/hɜːrˈmaɪəni/",
  "phonetic_spelling": "her-MY-uh-nee",
  "context_note": "Character name",
  "is_global": false
}
```

**Response (200):**
```json
{"id": "uuid", "created": true}
```
or
```json
{"id": "uuid", "updated": true}
```

**Example:**
```bash
curl -X POST https://api.acxcity.com/v1/projects/880e8400-.../lexicon \
  -H "Content-Type: application/json" \
  -d '{"word":"Hermione","ipa_phoneme":"/hɜːrˈmaɪəni/"}'
```

---

#### DELETE `/v1/projects/:id/lexicon/:entry_id`

Delete a pronunciation lexicon entry.

**Auth Required:** No

**Response (200):**
```json
{"deleted": true}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Entry not found or doesn't belong to this project |

**Example:**
```bash
curl -X DELETE https://api.acxcity.com/v1/projects/880e8400-.../lexicon/entry-uuid
```

---

### 3.4 Voices

#### GET `/v1/voices`

Browse the stock voice catalog with optional filters.

**Auth Required:** No

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | — | Filter by provider (e.g., `edge`, `polly`) |
| `gender` | string | — | Filter by gender |
| `accent` | string | — | Filter by accent |
| `is_active` | bool | `true` | Filter by active status |
| `limit` | int | `50` | Max results (1-200) |
| `offset` | int | `0` | Pagination offset |

**Response (200):**
```json
[
  {
    "id": "uuid",
    "slug": "en-US-AriaNeural",
    "display_name": "Aria",
    "gender": "Female",
    "accent": "American",
    "age_range": "Young Adult",
    "style_tags": ["narration", "conversational"],
    "description": "A versatile female voice",
    "provider": "edge",
    "sample_audio_url": "https://...",
    "languages": ["en-US"],
    "emotion_tags": ["happy", "sad", "excited"],
    "is_cloneable": true
  }
]
```

**Example:**
```bash
curl "https://api.acxcity.com/v1/voices?provider=edge&gender=Female&limit=10"
```

---

#### GET `/v1/voices/:id`

Get voice detail with emotion tags, sample URL, and provider voice ID.

**Auth Required:** No

**Response (200):**
```json
{
  "id": "uuid",
  "slug": "en-US-AriaNeural",
  "display_name": "Aria",
  "gender": "Female",
  "accent": "American",
  "age_range": "Young Adult",
  "style_tags": ["narration"],
  "description": "A versatile female voice",
  "provider": "edge",
  "provider_voice_id": "en-US-AriaNeural",
  "sample_audio_url": "https://...",
  "languages": ["en-US"],
  "emotion_tags": ["happy", "sad"],
  "is_cloneable": true,
  "source": "catalog"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Voice not found |

**Example:**
```bash
curl https://api.acxcity.com/v1/voices/uuid
```

---

#### POST `/v1/voices/:id/preview`

Generate a preview audio clip for a specific stock voice.

**Auth Required:** No

**Request Body:**
```json
{
  "text": "Hello, this is a preview.",
  "voice_id": "en-US-AriaNeural",
  "voice_slug": "en-US-AriaNeural",
  "emotion": "happy",
  "duration_seconds": 5.0
}
```

---

### 3.5 Clones

#### GET `/v1/voices/clones`

List voice clones for an organization.

**Auth Required:** No

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `organization_id` | string | ✅ | Organization UUID |

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "My Custom Voice",
    "status": "ready",
    "provider": "fish_speech",
    "reference_duration_seconds": 30.0,
    "safety_similarity_score": 0.85,
    "created_at": "2026-08-01T12:00:00Z"
  }
]
```

**Example:**
```bash
curl "https://api.acxcity.com/v1/voices/clones?organization_id=org-uuid"
```

---

#### POST `/v1/voices/clone`

Upload reference audio and create a voice clone.

**Auth Required:** No

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `organization_id` | string | ✅ | Organization UUID |

**Status:** `501 Not Implemented` — Voice cloning is planned for Phase 10.

---

### 3.6 Chapters

#### POST `/v1/chapters/:id/rerender`

Re-render a single chapter (or paragraph range) through the pipeline.

**Auth Required:** No

**Request Body:**
```json
{
  "paragraph_start": 0,
  "paragraph_end": 10
}
```

**Response (200):**
```json
{
  "chapter_id": "uuid",
  "task_id": "celery-task-id",
  "status": "rerendering"
}
```

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Chapter, job, or project not found |

**Example:**
```bash
curl -X POST https://api.acxcity.com/v1/chapters/chapter-uuid/rerender \
  -H "Content-Type: application/json" \
  -d '{"paragraph_start": 0, "paragraph_end": 5}'
```

---

#### GET `/v1/chapters/:id/waveform`

Get waveform JSON data for WaveSurfer.js rendering.

**Auth Required:** No

**Response (200):**
```json
{
  "chapter_id": "uuid",
  "duration_seconds": 320.5,
  "sample_rate": 24000,
  "peaks": [],
  "markers": []
}
```

> **Note:** `peaks` and `markers` are populated from pre-computed data when available.

**Errors:**
| Code | Condition |
|------|-----------|
| `404` | Chapter not found |

**Example:**
```bash
curl https://api.acxcity.com/v1/chapters/chapter-uuid/waveform
```

---

### 3.7 Health

#### GET `/v1/health`

Health check for the FastAPI sidecar.

**Auth Required:** No

**Response (200):**
```json
{
  "status": "ok",
  "service": "acx-city-v1",
  "version": "1.0.0"
}
```

**Example:**
```bash
curl https://api.acxcity.com/v1/health
```

---

## 4. MCP Tools

> MCP server runs as a separate process on port 8765. All requests require `Authorization: Bearer <MCP_API_KEY>`.
>
> **Required env vars:** `MCP_ENABLED=true`, `MCP_API_KEY=<key>`

### Tool Reference

#### `acx_health` (read-only)

Check platform health: database reachability and available TTS providers.

**Parameters:** None

**Returns:**
```json
{
  "status": "healthy",
  "database": "ok",
  "providers": [
    {"name": "edge", "available": true, "paid": false},
    {"name": "polly", "available": true, "paid": true}
  ]
}
```

---

#### `acx_list_jobs` (read-only)

List synthesis jobs, newest first.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `status` | string | ❌ | — | Filter: `queued`, `running`, `succeeded`, `needs_review`, `failed`, `canceled` |
| `organization_id` | string | ❌ | — | Filter to one organization UUID |
| `limit` | int | ❌ | `20` | Max results (1-100) |

**Returns:**
```json
{
  "count": 20,
  "jobs": [
    {
      "job_id": "uuid",
      "project_id": "uuid",
      "organization_id": "uuid",
      "status": "running",
      "progress": 45,
      "provider": "edge",
      "voice_id": "en-US-AriaNeural",
      "chapters_count": 12,
      "current_chapter": 5,
      "attempts": 1,
      "error": null,
      "created_at": "2026-08-07T06:00:00Z",
      "updated_at": "2026-08-07T06:05:00Z"
    }
  ]
}
```

**Errors:**
```json
{"error": "Unknown status 'invalid'. Valid: queued, running, succeeded, needs_review, failed, canceled"}
{"error": "'not-a-uuid' is not a valid organization UUID. Use acx_list_organizations to browse ids."}
```

---

#### `acx_get_job` (read-only)

Get one job with full detail including per-chapter status and QC results.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | string | ✅ | Job UUID |

**Returns:**
```json
{
  "job_id": "uuid",
  "status": "succeeded",
  "chapters": [
    {
      "index": 0,
      "title": "Chapter 1",
      "status": "done",
      "qc_passed": true,
      "qc_issues": null
    }
  ]
}
```

**Errors:**
```json
{"error": "'bad-id' is not a valid job UUID. Use acx_list_jobs to browse ids."}
{"error": "Job 'uuid' not found. Use acx_list_jobs to browse ids."}
```

---

#### `acx_list_organizations` (read-only)

List organizations with job counts. Useful for scoping other tool calls.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | int | ❌ | `50` | Max results (1-200) |

**Returns:**
```json
{
  "count": 15,
  "organizations": [
    {
      "id": "uuid",
      "name": "My Studio",
      "jobs": 42,
      "monthly_char_quota": 5000000
    }
  ]
}
```

---

#### `acx_usage` (read-only)

Get an organization's synthesis usage and quota for a month.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `organization_id` | string | ✅ | — | Organization UUID |
| `period` | string | ❌ | current month | Month as `YYYY-MM` |

**Returns:**
```json
{
  "period": "2026-08",
  "characters": 1250000,
  "cost_usd": 12.50,
  "quota": 5000000,
  "remaining": 3750000
}
```

**Errors:**
```json
{"error": "'bad-id' is not a valid organization UUID. Use acx_list_organizations to browse ids."}
{"error": "Organization 'uuid' not found. Use acx_list_organizations to browse ids."}
```

---

#### `acx_cancel_job` (write)

Cancel a running or queued synthesis job.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | string | ✅ | Job UUID to cancel |

**Returns:**
```json
{
  "job_id": "uuid",
  "status": "canceled",
  "message": "Job cancellation requested."
}
```

**Errors:**
```json
{"error": "Job is already succeeded. Cannot cancel."}
```

---

#### `acx_approve_job` (write)

Approve a job held in `needs_review` (QC gate).

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | string | ✅ | Job UUID to approve |

**Returns:**
```json
{
  "job_id": "uuid",
  "status": "succeeded",
  "message": "Job approved."
}
```

**Errors:**
```json
{"error": "Job status is 'running', not 'needs_review'."}
```

---

#### `acx_enqueue_synthesis` (write)

Enqueue a new synthesis job for an existing project.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project_id` | string | ✅ | — | Project UUID |
| `provider` | string | ❌ | `"edge"` | TTS provider (`edge`, `polly`, `kokoro`, `fish_speech`) |
| `voice_id` | string | ❌ | `"en-US-AriaNeural"` | Voice identifier |
| `formats` | string | ❌ | `"mp3,m4b"` | Comma-separated output formats |

**Returns:**
```json
{
  "job_id": "uuid",
  "status": "queued",
  "provider": "edge",
  "voice_id": "en-US-AriaNeural",
  "message": "Synthesis job enqueued."
}
```

**Errors:**
```json
{"error": "Project 'uuid' not found."}
{"error": "Project has no source text to synthesize."}
```

---

#### `acx_get_pipeline_status` (read-only)

Get multi-agent pipeline status for a project.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_id` | string | ✅ | Project UUID |

**Returns:**
```json
{
  "job_id": "uuid",
  "project_id": "uuid",
  "chapters_total": 12,
  "chapters_completed": 10,
  "chapters_failed": 0,
  "total_cost_usd": 0.0045,
  "traces": [
    {"chapter": 1, "status": "completed", "qa_passed": true},
    {"chapter": 2, "status": "completed", "qa_passed": true}
  ]
}
```

**Errors:**
```json
{"error": "Project 'uuid' not found."}
{"error": "No job found for this project."}
```

---

## 5. Common Schemas

### Job Status Lifecycle

```
queued ──► running ──► succeeded
                │
                ├──► needs_review ──► succeeded  (approve)
                │                  └──► failed    (reject)
                │
                └──► failed
                
queued/running ──► canceled  (user cancel)

running ──► queued  (retry after recoverable failure)
```

### Job Object

```json
{
  "task_id": "uuid",
  "job_id": "uuid",
  "project_id": "uuid",
  "status": "queued|running|succeeded|needs_review|failed|canceled",
  "progress": 0-100,
  "provider": "edge|polly|kokoro|fish_speech|voice-city",
  "voice_version_id": "uuid|null",
  "voice_display_name": "string|null",
  "voice_parameter_fingerprint": "string|null",
  "chapters_count": 12,
  "current_chapter": 5,
  "chapters": [ChapterResult],
  "cached_chunks": 150,
  "synthesized_chunks": 300,
  "formats": ["mp3", "m4b"],
  "qc_issues": [{"chapter": "string", "issues": ["string"]}],
  "attempts": 1,
  "error": "string|null"
}
```

### Chapter Result Object

```json
{
  "index": 0,
  "title": "Chapter 1",
  "status": "pending|processing|done|skipped|failed",
  "cached_chunks": 15,
  "total_chunks": 15,
  "qc": {
    "duration_s": 320.5,
    "loudness_dbfs": -18.2,
    "peak_dbfs": -3.1,
    "silence_ratio": 0.08,
    "clipping": false,
    "issues": [],
    "passed": true
  }
}
```

### Pipeline Trace Object

```json
{
  "chapter_number": 1,
  "status": "completed|failed|processing",
  "current_agent": "string|null",
  "agents": {
    "structure_parser": {"ms": 120},
    "character_attribution": {"ms": 340, "cost_usd": 0.0012},
    "text_normalizer": {"ms": 85, "cost_usd": 0.0003},
    "prosody_planner": {"ms": 200, "cost_usd": 0.0008},
    "qa_validator": {"ms": 95, "cost_usd": 0.0}
  },
  "characters_in": 5200,
  "characters_out": 5150,
  "qa_passed": true,
  "qa_issues": null,
  "qa_completeness_score": 0.98,
  "error": null
}
```

### UUIDs

All entity IDs are UUIDv4 strings (e.g., `550e8400-e29b-41d4-a716-446655440000`). Invalid UUIDs are rejected early with descriptive errors.

---

## 6. Error Handling

### Standard Error Response

All endpoints return errors in a consistent JSON format:

```json
{
  "error": "Human-readable error message"
}
```

### HTTP Status Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| `200` | OK | Successful read/update |
| `201` | Created | Successful creation |
| `202` | Accepted | Async operation accepted |
| `302` | Redirect | `?redirect=1` download flows |
| `400` | Bad Request | Validation errors, missing required fields |
| `401` | Unauthorized | Missing or invalid auth token |
| `402` | Payment Required | Monthly quota exceeded |
| `403` | Forbidden | Resource not found or access denied (deliberately ambiguous to prevent enumeration) |
| `404` | Not Found | Resource doesn't exist |
| `409` | Conflict | Invalid state transition |
| `415` | Unsupported Media Type | Invalid upload file type |
| `416` | Range Not Satisfiable | Invalid HTTP Range header |
| `429` | Too Many Requests | Rate limit exceeded (includes `Retry-After` header) |
| `500` | Internal Server Error | Unexpected server failure |
| `501` | Not Implemented | Feature not yet available |
| `503` | Service Unavailable | Health check degradation |

### Request ID

Every request/response cycle includes an `X-Request-Id` header for tracing. If the client sends one, it is reused; otherwise, the server generates one.

---

## 7. Rate Limiting & Quotas

### Rate Limits

| Resource | Limit | Window |
|----------|-------|--------|
| `POST /api/synthesize` | 30 requests per org | 60 seconds |

When rate-limited, the response includes:
- `Retry-After` header (seconds)
- Body: `{"error": "Rate limit exceeded. Please slow down.", "retry_after": 42}`

### Monthly Quotas

- Quotas are per-organization, per calendar month
- Free providers (e.g., `edge`) do **not** count against quota
- Paid providers consume characters from the org's monthly allowance
- Default quota: configurable via `QUOTA_MONTHLY_CHARS` env var
- Per-org overrides via `Organization.monthly_char_quota`
- Exceeded quota returns `402 Payment Required` with usage details:
  ```json
  {
    "error": "Monthly usage quota exceeded",
    "used": 4800000,
    "quota": 5000000,
    "requested": 300000
  }
  ```

---

## Appendix: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_ENABLED` | `false` | Enable MCP server |
| `MCP_API_KEY` | — | MCP authentication key |
| `MCP_HOST` | `0.0.0.0` | MCP server bind host |
| `MCP_PORT` | `8765` | MCP server port |
| `SIGNED_URL_TTL_SECONDS` | `3600` | Signed URL expiration |
| `SYNTHESIZE_RATE_LIMIT` | `30` | Jobs per rate window |
| `SYNTHESIZE_RATE_WINDOW_SECONDS` | `60` | Rate limit window |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | CORS origins (comma-separated or `*`) |
| `UPLOAD_FOLDER` | `uploads` | Upload staging directory |
| `CACHE_FOLDER` | `cache` | Synthesis cache directory |
| `OUTPUT_FOLDER` | `outputs` | Pipeline output directory |
| `FLASK_ENV` | — | Set to `development` for debug mode |
| `HOST` | `0.0.0.0` | Flask server bind host |
| `PORT` | `5000` | Flask server port |
