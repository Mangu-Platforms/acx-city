# ACX City — Implementation Guide

**Purpose:** Operationalize the remediation plan. This document is the companion to `ACX_CITY_REMEDIATION_PLAN.md`. It provides:
- Machine-checkable exit gates (exact bash commands)
- Database schemas and migrations
- Code templates and structure
- Work-breakdown and task sequencing
- Rollback procedures
- Monitoring hooks

**For each phase, three sections:**
1. **Scope** — what changes, what doesn't
2. **Implementation** — step by step with file paths
3. **Verification** — how to know it's done

---

## P0.0: Get `main` green

**Status:** Blocker for everything. All other phases depend on this. Rough estimate: 1–2 days.

### Scope

Fix five independent defects in three separate build jobs. No architectural changes.

| Defect | File | Type | Fix |
|---|---|---|---|
| Frontend TS error: missing `provider_voice_id` | `frontend/src/App.tsx:131` | Missing field on type | Add to `StockVoice` typedef or remove the call |
| Frontend TS error: unknown page type | `frontend/src/App.tsx:170` | Type mismatch | Update `Workspace` type to include "characters" etc. |
| Dashboard missing `'use client'` | `dashboard/app/dashboard/pipeline/page.tsx:1` | Next.js directive | Add `'use client'` at top |
| Dashboard wrong import path | Same file `:2` | Path error | Change `../../lib/api` to `../../../lib/api` |
| Dashboard missing dep | Same file `:3` | Missing package | Add `lucide-react` to `dashboard/package.json` |
| Dashboard implicit `any` | Same file `:37` | TS error | Add type annotation to `res` param |
| Dashboard unknown type | Same file `:41` | Type unknown | Replace `res.data` with proper type |
| Backend EPUB failures (×5) | `backend/services/epub_generator.py:92` | ORM mismatch | Replace `len(self.book.chapters)` with `len([c for c in self.book.items if isinstance(c, epub.EpubHtml)])` or use the ebooklib API correctly |
| Backend GPU synthesis tests (×2) | `backend/tests/test_services.py` | Environment | May be sandbox artifact; verify on GitHub Actions |

### Implementation

#### 1.1 — Frontend App.tsx (two errors)

**Inspect the error context:**

```bash
cd acx-city/frontend
npx tsc --noEmit 2>&1 | grep -A2 "App.tsx"
```

**Inspect the `StockVoice` typedef:**

```bash
grep -n "provider_voice_id\|export.*interface StockVoice" src/lib/schemas.ts src/types/index.ts src/types/*.ts 2>/dev/null | head -20
```

**Option A:** If `provider_voice_id` should be there — add it to the typedef.
**Option B:** If the call should not reference it — remove `.provider_voice_id` from the call.

**Fix the page type error:**

```bash
grep -n "type Page\|type Workspace" src/App.tsx src/types/*.ts
```

**Update the type to include the three missing pages: `"characters" | "lexicon" | "production"`.**

**Verify:**

```bash
cd frontend && npm run build  # must exit 0
```

#### 1.2 — Dashboard pipeline page (five errors)

**Add the directive and fix the import:**

```bash
cd acx-city/dashboard
# Line 1: add 'use client'
# Line 2: change import path from ../../lib/api to ../../../lib/api
```

**Add the missing dependency:**

```bash
# In dashboard/package.json, under dependencies:
# "lucide-react": "^0.xxx" (match version from frontend package.json)
npm install
```

**Fix the parameter types and unknown reads:**

At line 37:

```typescript
const res = await api.get(`/api/jobs`) as { data?: { jobs?: any[] } };
```

At line 41:

```typescript
const uniqueProjects = [...new Map((res.data?.jobs || []).map(...))]
```

**Verify:**

```bash
npx tsc --noEmit && npx next build  # must exit 0
```

#### 1.3 — Backend EPUB generator

**Read the exact error:**

```bash
cd backend
export JWT_SECRET=ci-test && pytest tests/test_epub_generator.py -q 2>&1 | head -20
```

**The issue:** `EpubBook` doesn't have a `.chapters` attribute in `ebooklib==0.18`. Use the correct ebooklib API:

```python
# Instead of:
chapter_num = len(self.book.chapters) + 1

# Use:
html_chapters = [item for item in self.book.items if isinstance(item, epub.EpubHtml)]
chapter_num = len(html_chapters) + 1
```

**Verify:**

```bash
pytest tests/test_epub_generator.py -q  # must pass
```

#### 1.4 — Backend GPU synthesis tests (optional)

These may be environment artifacts (pyOpenSSL version conflict in the sandbox). If they consistently fail:

```bash
# Check the error detail
pytest tests/test_services.py::TestGPUSynthesis -v 2>&1 | head -40
```

If it's `AttributeError: module 'lib' has no attribute 'X509_V_FLAG_NOTIFY_POLICY'`:
- This is a cryptography/pyOpenSSL mismatch, not repository code.
- Run the same tests in GitHub Actions (the official CI environment).
- If they pass there, the repository is fine and the gate is satisfied.
- If they fail there too, file a separate issue to fix the dependency versions.

**Do not spend engineering time on this in P0.0; it blocks nothing.**

### Verification (exit gate)

```bash
cd acx-city

# Backend
(cd backend && export JWT_SECRET=test && pytest -q 2>&1 | tail -1)
# Expected: "119 passed" (ignore sandbox env failures if any)

# Frontend
(cd frontend && npm run build 2>&1 | tail -1)
# Expected: exit 0, no errors

# Dashboard
(cd dashboard && npm install --silent && npx next build 2>&1 | tail -1)
# Expected: exit 0, build successful
```

**All three must exit 0. When they do, P0.0 is complete.**

---

## P0.1: Freeze expansion + matrix + disable autonomous workflow

**Estimate:** 0.5 days (mostly review/admin).

### Scope

1. Publish `docs/CAPABILITY_MATRIX.md` (copy from plan).
2. Add branch protection rule: all CI jobs required.
3. Disable `.github/workflows/main.yml` (rename to `.disabled/`).
4. Document in `README.md` why.

### Implementation

#### 1.1 — Add the capability matrix

```bash
cp ACX_CITY_REMEDIATION_PLAN.md > acx-city/docs/CAPABILITY_MATRIX.md
# Keep only the table from §3; add a note at the top:
# "This matrix is the release gate for ACX City. A feature cannot merge
#  until its row is all-Yes. Updated as each phase completes."
```

#### 1.2 — Branch protection

In GitHub: Settings → Branches → main → Add rule
- Require status checks to pass before merging
- Select: `ci.yml` (all three jobs)
- Dismiss stale pull request approvals
- Require branches to be up to date before merging

#### 1.3 — Disable the workflow

```bash
cd acx-city
mkdir -p .github/disabled
mv .github/workflows/main.yml .github/disabled/main.yml.disabled

# Add to README.md deployment section:
# "Daily multi-agent workflow disabled as of [date]. It generated
#  unreviewable churn against a non-building codebase. Reconsidered
#  after P1.8 (dashboard rebuild) if measurement justifies it."
```

### Verification

```bash
# 1. Matrix exists and is readable
cat acx-city/docs/CAPABILITY_MATRIX.md | head -30

# 2. main.yml is gone from active workflows
ls -la .github/workflows/ | grep main.yml  # Should NOT appear

# 3. Branch protection rule exists
# (verify in GitHub UI under Settings → Branches)

# 4. Next PR requires passing CI (verify on next PR submission)
```

---

## P0.2: Durable chapter artifacts

**Estimate:** 3–4 days.

**This is the largest structural change. Everything downstream depends on it. Do NOT parallelize with P0.3.**

### Scope

1. Add columns to `ChapterResult`: `audio_key`, `audio_sha256`, `audio_bytes`, `content_type`, `synthesis_id`.
2. Modify `jobs/pipeline.py` to upload chapter audio to object storage before moving to the next chapter.
3. Modify resume logic to check storage before re-synthesizing.
4. Update tests.

### Schema changes

**New migration** (`backend/migrations/versions/`):

```python
# Migration: Add durable chapter artifacts

def upgrade():
    op.add_column('chapter_results', sa.Column('audio_key', sa.String(512), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_sha256', sa.String(64), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_bytes', sa.Integer, nullable=True))
    op.add_column('chapter_results', sa.Column('content_type', sa.String(100), nullable=True))
    op.add_column('chapter_results', sa.Column('synthesis_id', sa.String(64), nullable=True))
    # Unique constraint: a chapter can have at most one synthesis_id per revision
    op.create_unique_constraint('uq_chapter_synthesis_id', 'chapter_results', ['job_id', 'index', 'synthesis_id'])

def downgrade():
    op.drop_constraint('uq_chapter_synthesis_id', 'chapter_results')
    op.drop_column('chapter_results', 'synthesis_id')
    op.drop_column('chapter_results', 'content_type')
    op.drop_column('chapter_results', 'audio_bytes')
    op.drop_column('chapter_results', 'audio_sha256')
    op.drop_column('chapter_results', 'audio_key')
```

**Update `ChapterResult` model:**

```python
# backend/db/models.py

audio_key: Mapped[Optional[str]] = mapped_column(String(512))  # S3/storage key
audio_sha256: Mapped[Optional[str]] = mapped_column(String(64))  # hex digest
audio_bytes: Mapped[Optional[int]] = mapped_column(Integer)  # file size
content_type: Mapped[Optional[str]] = mapped_column(String(100))  # audio/mpeg etc
synthesis_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # deterministic ID
```

### Implementation

#### 2.1 — Pipeline changes

**Create helper function** in `jobs/pipeline.py`:

```python
def _upload_chapter_audio(session: Session, job: Job, chapter_row: ChapterResult,
                          chapter_index: int, audio_path: str) -> str:
    """Upload chapter audio to storage and record metadata.
    
    Returns the storage key.
    Raises on any failure; caller handles retry.
    """
    storage = get_storage()
    
    # Verify the file exists and is decodable
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Chapter audio not found: {audio_path}")
    
    # Compute checksum
    with open(audio_path, 'rb') as f:
        audio_bytes = f.read()
    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    
    # Validate the audio (lightweight check)
    qc = _audio.qc_check(audio_path)
    if not qc.get('duration_s'):
        raise ValueError(f"Chapter {chapter_index}: audio has no decodable duration")
    
    # Upload to storage
    key = _output_key(job, f"chapters/{chapter_index:03d}.mp3")
    storage.put_bytes(key, audio_bytes, content_type="audio/mpeg")
    
    # Record metadata on the chapter row
    chapter_row.audio_key = key
    chapter_row.audio_sha256 = audio_sha256
    chapter_row.audio_bytes = len(audio_bytes)
    chapter_row.content_type = "audio/mpeg"
    
    return key
```

**Modify the resume logic** in `run_job()`:

```python
# OLD:
if row.status == ChapterStatus.done:
    path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
    if os.path.exists(path):
        chapter_files.append(path); chapter_titles.append(chapter["title"]); continue

# NEW:
if row.status == ChapterStatus.done:
    # Prefer to fetch from storage (durable)
    if row.audio_key:
        try:
            audio_bytes = storage.get_bytes(row.audio_key)
            # Verify integrity
            if hashlib.sha256(audio_bytes).hexdigest() == row.audio_sha256:
                # Temporarily write to local path for assembly
                path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
                with open(path, 'wb') as f:
                    f.write(audio_bytes)
                chapter_files.append(path)
                chapter_titles.append(chapter["title"])
                continue
        except Exception as e:
            log.warning(f"Failed to fetch chapter {i} from storage, will re-synthesize: {e}")
    
    # Fallback: local disk
    path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
    if os.path.exists(path):
        chapter_files.append(path); chapter_titles.append(chapter["title"]); continue
```

**Add upload call after chapter assembly:**

```python
# After line "session.commit()  # durable per-chapter checkpoint"

try:
    _upload_chapter_audio(session, job, row, i, chapter_path)
except Exception as e:
    log.error(f"Failed to upload chapter {i}: {e}; retrying synthesis on next run")
    row.status = ChapterStatus.pending  # Mark for re-synthesis
    row.audio_key = None
    
session.commit()
```

#### 2.2 — Test changes

**New test** in `backend/tests/test_jobs.py`:

```python
def test_chapter_audio_survives_local_disk_wipe(session, job_with_project):
    """Verify that chapter audio in storage is recovered even if local disk is cleared."""
    job = job_with_project
    
    # Run the job to completion
    with session_scope() as s:
        job = s.merge(job)
        assert run_job(s, job, lambda: True)
    
    # Verify chapters are uploaded
    for chapter in job.chapters:
        assert chapter.audio_key is not None
        assert chapter.audio_sha256 is not None
    
    # Simulate disk wipe
    task_dir = os.path.join(OUTPUT_FOLDER, job.id)
    if os.path.exists(task_dir):
        shutil.rmtree(task_dir)
    
    # Re-run the job; should not re-synthesize
    usage_before = _count_usage_events(session, job.organization_id)
    
    with session_scope() as s:
        job = s.merge(job)
        # Calling run_job again without resetting the job status
        # should recognize all chapters are done and skip synthesis
        assert run_job(s, job, lambda: True)
    
    usage_after = _count_usage_events(session, job.organization_id)
    assert usage_after == usage_before, "Chapter re-synthesis occurred"
```

### Verification (exit gate)

**Machine-checkable:**

```bash
cd acx-city/backend

# 1. Migration applies
alembic upgrade head  # must succeed

# 2. Model loads
python -c "from db.models import ChapterResult; print(ChapterResult.audio_key)"

# 3. Test passes
export JWT_SECRET=test
pytest tests/test_jobs.py::test_chapter_audio_survives_local_disk_wipe -v

# 4. Existing tests still pass
pytest tests/test_pipeline.py -q
```

**Manual verification:**

```bash
# Run a real job, verify chapters are uploaded
# (requires a running instance with object storage configured)
curl http://localhost:5000/api/health  # → healthy
# Upload a book, start synthesis
# Verify chapter_results rows have audio_key, audio_sha256 populated
# Wipe OUTPUT_FOLDER; restart the job; verify no re-synthesis in logs/metrics
```

---

## P0.3: One Flask `/api` surface

**Estimate:** 4–5 days.

**Prerequisite:** P0.2 must be done first (no circular dependencies).

### Scope

1. Extract business logic from `backend/v1_api.py` into `backend/services/*.py`.
2. Create thin Flask blueprints around them.
3. Mount on `/api` (not `/v1`).
4. Delete `v1_api.py` and its Uvicorn entrypoint.
5. Remove all `/v1` calls from frontend and dashboard.

### Implementation

#### 3.1 — Extract services

**Create** `backend/services/character_service.py`:

```python
"""Character voice assignments."""
from sqlalchemy.orm import Session
from db.models import Project
from db.voxengine_models import CharacterVoiceMap

class CharacterVoiceService:
    def __init__(self, session: Session):
        self.session = session
    
    def list_characters(self, project_id: str) -> list[dict]:
        """List all character-to-voice assignments for a project."""
        chars = self.session.query(CharacterVoiceMap).filter(
            CharacterVoiceMap.project_id == project_id
        ).all()
        return [
            {
                "id": c.id,
                "character_name": c.character_name,
                "voice_id": c.voice_id,
                "voice_slug": c.voice_slug,
                "pitch_adjustment": float(c.pitch_adjustment),
                "speed_adjustment": float(c.speed_adjustment),
                "base_emotion": c.base_emotion,
                "is_narrator": c.is_narrator,
                "notes": c.notes,
            }
            for c in chars
        ]
    
    def set_character(self, project_id: str, character_name: str, **kwargs) -> dict:
        """Create or update a character assignment."""
        existing = self.session.query(CharacterVoiceMap).filter(
            CharacterVoiceMap.project_id == project_id,
            CharacterVoiceMap.character_name == character_name,
        ).first()
        
        if existing:
            for k, v in kwargs.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.session.flush()
            char = existing
        else:
            char = CharacterVoiceMap(project_id=project_id, character_name=character_name, **kwargs)
            self.session.add(char)
            self.session.flush()
        
        return {
            "id": char.id,
            "character_name": char.character_name,
            "voice_id": char.voice_id,
            # ... full response as above
        }
```

**Create** `backend/services/lexicon_service.py`:

```python
"""Pronunciation lexicon."""
from sqlalchemy.orm import Session
from db.voxengine_models import PronunciationLexicon

class LexiconService:
    def __init__(self, session: Session):
        self.session = session
    
    def list_lexicon(self, project_id: str) -> list[dict]:
        entries = self.session.query(PronunciationLexicon).filter(
            PronunciationLexicon.project_id == project_id
        ).all()
        return [
            {
                "id": e.id,
                "word": e.word,
                "ipa_phoneme": e.ipa_phoneme,
                "phonetic_spelling": e.phonetic_spelling,
                "context_note": e.context_note,
                "source": e.source,
                "is_global": e.is_global,
            }
            for e in entries
        ]
    
    def add_entry(self, project_id: str, word: str, **kwargs) -> dict:
        """Add or update a lexicon entry."""
        entry = PronunciationLexicon(project_id=project_id, word=word, **kwargs)
        self.session.add(entry)
        self.session.flush()
        return {"id": entry.id, "word": entry.word, ...}
    
    def delete_entry(self, project_id: str, entry_id: str) -> None:
        entry = self.session.query(PronunciationLexicon).filter(
            PronunciationLexicon.id == entry_id,
            PronunciationLexicon.project_id == project_id,
        ).first()
        if entry:
            self.session.delete(entry)
            self.session.flush()
```

**Repeat for:**
- `voice_service.py` (list voices, get voice)
- `preview_service.py` (rewrite synchronously)
- `rerender_service.py` (rewrite to not use Celery)
- `pipeline_service.py` (list/get pipeline status + traces)

#### 3.2 — Create Flask blueprints

**Create** `backend/api/characters.py`:

```python
from flask import Blueprint, jsonify, request
from auth import require_auth, current_identity
from db import get_session
from services.character_service import CharacterVoiceService

bp = Blueprint('characters', __name__, url_prefix='/api/projects')

@bp.route('/<project_id>/characters', methods=['GET'])
@require_auth
def list_characters(project_id):
    identity = current_identity()
    session = get_session()
    
    project = _get_owned_project(session, project_id, identity.org.id)
    service = CharacterVoiceService(session)
    return jsonify(service.list_characters(project_id))

@bp.route('/<project_id>/characters', methods=['POST'])
@require_auth
def set_character(project_id):
    identity = current_identity()
    session = get_session()
    
    project = _get_owned_project(session, project_id, identity.org.id)
    data = request.json
    service = CharacterVoiceService(session)
    result = service.set_character(project_id, **data)
    session.commit()
    return jsonify(result), 201
```

**Register in `app.py`:**

```python
from api.characters import bp as characters_bp
from api.lexicon import bp as lexicon_bp
# ... etc

app.register_blueprint(characters_bp)
app.register_blueprint(lexicon_bp)
```

#### 3.3 — Update frontend/dashboard

**Search and replace all `/v1` with `/api`:**

```bash
find frontend/src dashboard/app -name "*.ts" -o -name "*.tsx" | xargs sed -i 's|/v1/|/api/|g'
```

**Verify no `/v1` remains:**

```bash
grep -r "/v1" frontend/src dashboard --include="*.ts" --include="*.tsx"  # Should return nothing
```

#### 3.4 — Update the client APIs

**`dashboard/lib/api.ts`:** Add methods for the new endpoints (characters, lexicon, pipeline status).

```typescript
export const api = {
  // ... existing methods
  
  characters: (projectId: string) =>
    req<CharacterAssignment[]>(`/api/projects/${projectId}/characters`),
  
  setCharacter: (projectId: string, char: CharacterAssignmentRequest) =>
    req<CharacterAssignment>(`/api/projects/${projectId}/characters`, {
      method: 'POST',
      body: JSON.stringify(char),
    }),
  
  pipelineStatus: (projectId: string) =>
    req<PipelineStatusResponse>(`/api/projects/${projectId}/pipeline`),
  
  // ... etc
}
```

### Verification (exit gate)

```bash
cd acx-city

# 1. v1_api.py is deleted
test ! -f backend/v1_api.py && echo "PASS: v1_api.py removed"

# 2. No /v1 in frontend/dashboard
grep -r "/v1" frontend/src dashboard && echo "FAIL: /v1 still present" || echo "PASS: No /v1"

# 3. Backend starts and has new routes
(cd backend && python -c "from app import app; app.url_map" | grep '/api/projects.*characters')

# 4. Tests still pass
(cd backend && pytest tests/test_api.py -q)

# 5. Frontend builds
(cd frontend && npm run build 2>&1 | grep -i error) && echo "FAIL" || echo "PASS"

# 6. Dashboard builds
(cd dashboard && npx next build 2>&1 | grep -i "error\|failed") && echo "FAIL" || echo "PASS"
```

---

## P0.4: Contract layer

**Estimate:** 2–3 days.

### Schema: Pydantic request/response models

**Create** `backend/api/contracts/models.py`:

```python
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

# Jobs
class JobResponse(BaseModel):
    job_id: str
    project_id: str
    status: str  # queued | running | succeeded | needs_review | failed | canceled
    progress: int
    provider: str
    voice_id: str
    chapters_count: int
    current_chapter: int
    formats: List[str]
    output_mp3_key: Optional[str] = None
    output_m4b_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class JobListResponse(BaseModel):
    jobs: List[JobResponse]
    total: int

# Characters
class CharacterAssignmentRequest(BaseModel):
    character_name: str
    voice_id: Optional[str] = None
    voice_slug: Optional[str] = None
    pitch_adjustment: float = 1.0
    speed_adjustment: float = 1.0
    base_emotion: str = "neutral"
    is_narrator: bool = False
    notes: Optional[str] = None

class CharacterAssignmentResponse(BaseModel):
    id: str
    project_id: str
    character_name: str
    voice_id: Optional[str]
    pitch_adjustment: float
    speed_adjustment: float
    base_emotion: str
    is_narrator: bool

# Lexicon
class LexiconEntryRequest(BaseModel):
    word: str
    ipa_phoneme: Optional[str] = None
    phonetic_spelling: Optional[str] = None
    context_note: Optional[str] = None

class LexiconEntryResponse(BaseModel):
    id: str
    project_id: str
    word: str
    ipa_phoneme: Optional[str]
    phonetic_spelling: Optional[str]

# Voices
class VoiceResponse(BaseModel):
    id: str
    provider: str
    provider_voice_id: str
    display_name: str
    language: str
    capabilities: List[str]  # synthesis, preview, cloning, etc

# Pipeline
class PipelineStatusResponse(BaseModel):
    job_id: str
    status: str
    chapters_total: int
    chapters_completed: int
    chapters_failed: int
    total_cost_usd: float
```

**Generate TypeScript types** in CI:

```bash
# .github/workflows/ci.yml, add a new job:

contract-codegen:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - name: Generate TypeScript types from Pydantic models
      run: |
        pip install pydantic datamodel-code-generator
        datamodel-code-generator --input backend/api/contracts/models.py \
          --input-file-type pydantic_v2 \
          --output generated/api-types.ts
    - name: Check for changes
      run: |
        if ! git diff-index --quiet HEAD; then
          echo "Generated types differ from committed version"
          exit 1
        fi
```

**Use in frontend:**

```typescript
// frontend/src/types/generated.ts (committed with the models)
import * as contracts from '../../backend/api/contracts/models.py'  // Pydantic
export type JobResponse = ...  // TypeScript equivalent
```

### Verification

```bash
# 1. Models load
python -c "from api.contracts.models import JobResponse"

# 2. TS types generated
ls frontend/src/types/generated.ts

# 3. Types are in sync (no diff in CI)
# (Verify on next PR)
```

---

## P0.5: Lease, heartbeat, orphan recovery

**Estimate:** 2–3 days.

### Schema changes

**New columns on `jobs` table:**

```python
# Migration
def upgrade():
    op.add_column('jobs', sa.Column('worker_id', sa.String(100), nullable=True))
    op.add_column('jobs', sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('last_error_code', sa.String(50), nullable=True))
    op.create_index('ix_jobs_lease', 'jobs', ['lease_expires_at'])
```

**New table `worker_heartbeats`:**

```python
def upgrade():
    op.create_table(
        'worker_heartbeats',
        sa.Column('worker_id', sa.String(100), primary_key=True),
        sa.Column('role', sa.String(50), default='synthesis'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('jobs_claimed', sa.Integer, default=0),
        sa.Column('version', sa.String(50)),
    )
```

### Implementation

**New heartbeat function** `backend/jobs/queue.py`:

```python
def heartbeat_worker(session: Session, worker_id: str, role: str = 'synthesis') -> bool:
    """Refresh the worker's heartbeat. Returns False if the worker should stop.
    
    This is separate from job leases. It answers: is this worker alive?
    """
    now = utcnow()
    
    # Upsert the heartbeat
    from db.models import WorkerHeartbeat
    hb = session.query(WorkerHeartbeat).filter_by(worker_id=worker_id).first()
    if hb:
        hb.heartbeat_at = now
    else:
        hb = WorkerHeartbeat(
            worker_id=worker_id,
            role=role,
            started_at=now,
            heartbeat_at=now,
            version=os.getenv('WORKER_VERSION', 'unknown'),
        )
        session.add(hb)
    session.flush()
    return True

def lease_job(session: Session, job: Job, worker_id: str, lease_seconds: int = 300) -> bool:
    """Refresh a job's lease (independent of heartbeat).
    
    Returns False if the job is no longer ours (lost to another worker or user canceled).
    """
    now = utcnow()
    updated = session.query(Job).filter(
        Job.id == job.id,
        Job.locked_by == worker_id,  # Guard: we still own it
        Job.status == JobStatus.running,  # Guard: it's still running
    ).update({
        'heartbeat_at': now,
        'lease_expires_at': now + timedelta(seconds=lease_seconds),
    })
    session.flush()
    return updated > 0  # 0 means we lost the lease
```

**Modify worker loop** `backend/worker.py`:

```python
def process_one(worker_id: str) -> bool:
    """Claim and run a single job."""
    
    # Heartbeat independent of job processing
    with session_scope() as session:
        q.heartbeat_worker(session, worker_id)
    
    with session_scope() as session:
        job = q.claim_next_job(session, worker_id)
        if job is None:
            return False
        job_id = job.id

    request_id_var.set(job_id)

    with session_scope() as session:
        from db.models import Job
        job = session.get(Job, job_id)

        def should_continue() -> bool:
            """Check heartbeat and lease. Return False to stop."""
            # Heartbeat first
            if not q.heartbeat_worker(session, worker_id):
                return False
            # Then lease
            if not q.lease_job(session, job, worker_id):
                log.warning("Lost lease on job %s", job_id)
                return False
            return True

        try:
            gate_passed = run_job(session, job, should_continue)
            if gate_passed:
                q.complete_job(session, job, worker_id)
            else:
                q.hold_for_review(session, job, worker_id)
        except JobCanceled:
            from db.models import JobStatus
            # CHANGED: only mark canceled if we still own the job
            affected = session.query(Job).filter(
                Job.id == job_id,
                Job.locked_by == worker_id,
            ).update({'status': JobStatus.canceled, 'locked_by': None})
            if affected:
                q._close_attempt(session, job, worker_id, outcome='canceled')
            else:
                log.warning("Job %s was stolen before we could cancel it", job_id)
        except Exception as e:
            session.rollback()
            with session_scope() as s2:
                j2 = s2.get(Job, job_id)
                q.fail_job(s2, j2, worker_id, str(e))
            log.exception("job %s failed", job_id)
    
    return True

def main() -> None:
    init_engine()
    worker_id = _worker_id()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("worker %s starting", worker_id)

    with session_scope() as session:
        q.heartbeat_worker(session, worker_id)
        q.recover_orphans(session)

    last_sweep = time.monotonic()
    while not _shutdown:
        try:
            process_one(worker_id)
        except Exception:
            log.exception("worker loop failed")

        now = time.monotonic()
        if now - last_sweep >= ORPHAN_SWEEP_INTERVAL:
            with session_scope() as session:
                q.recover_orphans(session)
            last_sweep = now

        time.sleep(POLL_INTERVAL)

    log.info("worker %s stopped", worker_id)
```

**Update orphan recovery** `backend/jobs/queue.py`:

```python
def recover_orphans(session: Session, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> int:
    """Requeue running jobs whose worker lease has expired."""
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    stale = session.query(Job).filter(
        Job.status == JobStatus.running,
        Job.lease_expires_at.is_not(None),
        Job.lease_expires_at < cutoff,
    ).all()
    
    # Mark the dead attempts
    for job in stale:
        last = session.query(JobAttempt).filter(
            JobAttempt.job_id == job.id,
            JobAttempt.finished_at.is_(None),
        ).order_by(JobAttempt.attempt_number.desc()).first()
        
        if last:
            last.finished_at = utcnow()
            last.outcome = 'orphaned'
    
    # Requeue or fail
    count = 0
    for job in stale:
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.failed
            job.error = "worker lease expired and max attempts exhausted"
        else:
            job.status = JobStatus.queued
            job.available_at = utcnow()
        job.locked_by = None
        job.locked_at = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        count += 1
    
    if count:
        session.flush()
        log.warning("recovered %d orphaned job(s)", count)
    return count
```

### Verification (exit gate)

**Test in P0.5:**

```python
def test_lease_renewal_independent_of_chapter_progress(session, job_with_project):
    """Verify that a 60-minute chapter doesn't timeout the job."""
    job = job_with_project
    worker_id = 'test-worker-1'
    
    with session_scope() as s:
        job = s.merge(job)
        job, _ = q.claim_next_job(s, worker_id), None
        
        # Simulate time advancing 5 min (half the lease)
        job.heartbeat_at = utcnow() - timedelta(minutes=5)
        s.commit()
        
        # Lease should still be valid
        with session_scope() as s2:
            result = q.lease_job(s2, job, worker_id)
            assert result is True
        
        # Simulate lease expiry
        job.heartbeat_at = utcnow() - timedelta(minutes=10)
        s.commit()
        
        # Now it should fail
        with session_scope() as s2:
            result = q.lease_job(s2, job, worker_id)
            assert result is False

def test_cancel_and_lease_loss_dont_collide(session, job_with_project):
    """Verify job isn't marked canceled if lease is already lost."""
    job = job_with_project
    worker_a = 'worker-a'
    worker_b = 'worker-b'
    
    with session_scope() as s:
        job = s.merge(job)
        job = q.claim_next_job(s, worker_a)
        assert job.locked_by == worker_a
    
    # Simulate lease expiry
    with session_scope() as s:
        job = session.get(Job, job.id)
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    
    # Orphan sweeper requeues it
    with session_scope() as s:
        q.recover_orphans(s)
    
    # Worker B claims it
    with session_scope() as s:
        job = q.claim_next_job(s, worker_b)
        assert job.locked_by == worker_b
    
    # Worker A tries to cancel (it's a LeaseLost exception internally)
    with session_scope() as s:
        job = session.get(Job, job.id)
        affected = session.query(Job).filter(
            Job.id == job.id,
            Job.locked_by == worker_a,  # This guard prevents the clobber
        ).update({'status': JobStatus.canceled})
        assert affected == 0, "Worker A should not be able to cancel"
        
        # Job is still running under Worker B
        job = session.get(Job, job.id)
        assert job.status == JobStatus.running
        assert job.locked_by == worker_b
```

**Machine-checkable:**

```bash
cd backend
pytest tests/test_jobs.py::test_lease_renewal_independent_of_chapter_progress -v
pytest tests/test_jobs.py::test_cancel_and_lease_loss_dont_collide -v
```

---

## P0.6 through P2.4: Summary and integration points

The above sections detail the first 5 phases in depth. Phases P0.6–P2.4 follow a similar pattern:

| Phase | Focus | Critical dependencies |
|---|---|---|
| P0.6 | Stage checkpoints + idempotent synthesis | P0.2 (chapter artifacts) |
| P0.7 | `FakeSpeechProvider` | None; orthogonal |
| P0.8 | Golden-path E2E test | P0.1–P0.7 complete |
| P1.1 | Media validation | P0.2 (chapter artifacts), P0.8 (test framework) |
| P1.2 | Multi-agent pipeline convergence | P0.3 (one API), P0.5 (real lease model) |
| P1.3 | Character/voice/lexicon integration | P0.3 (one API), P0.4 (contract layer) |
| P1.4 | Preview + streaming rewrite | P1.3 (voice service), P0.4 (contract) |
| P1.5 | Chapter revisions + rerender | P0.6 (stage checkpoints), P1.4 (preview) |
| P1.6 | Export repair (EPUB, MP3, M4B) | P0.2 (chapter artifacts), P0.4 (contract) |
| P1.7 | Dashboard rebuild | P0.3 (one API), P0.4 (contract), P1.6 (exports) |
| P1.8 | Liveness/readiness/worker heartbeat | P0.5 (heartbeat table), all prior |
| P2.1 | Voice cloning | P1.4 (preview), P1.8 (readiness) |
| P2.2 | Failure-injection suite | P0.7 (`FakeSpeechProvider`), P1.1 (media validation) |
| P2.3 | Cancellation granularity | P0.5 (cancel/lease-loss), all prior |
| P2.4 | Performance work | Measurement-driven; P2.1–P2.3 complete |
| P3 | Celery/Redis/K8s reconsideration | All of P1 and P2 complete |

For each phase, create a task card with:

```markdown
## Phase [X]: [Name]

**Scope:** [What changes]
**Blocker:** [What must be done first]
**Effort:** [est. days]

### Tasks

- [ ] Implementation subtask A (file:line range)
- [ ] Implementation subtask B
- [ ] Test coverage (file:lines)
- [ ] Documentation update
- [ ] Code review checklist
- [ ] Deploy/release notes

### Exit gate

**Machine-check:**
bash
...
```

---

## Integration and rollout strategy

### Rolling out to production

1. **All changes land on a branch** `remediation/p0-p1` until P1.8 is done.
2. **CI gates all merges** to that branch (no pushing to `main` until each phase passes).
3. **Staging deploys** at the end of each phase (verify the phase against a clone of production data).
4. **Production release** only after all of P0 (P0.0–P0.8) is complete and golden-path test is green for 50 runs.

### Monitoring during rollout

Each phase should add observability hooks:

| Phase | Metric | Alert threshold |
|---|---|---|
| P0.2 | Chapter upload failures | > 0 per hour |
| P0.5 | Orphan recovery events | trend (increasing = problem) |
| P0.6 | Duplicate synthesis (via UsageEvent) | > 0 per day |
| P0.8 | Golden-path test failures | > 1 per 50 runs |
| P1.1 | Media validation rejects | trend |
| P1.4 | Preview failures | > 10% error rate |
| P1.5 | Rerender cost per chapter | baseline |
| P1.8 | Worker heartbeat staleness | max 90s lag |

### Rollback procedure

**At any point before P2.0:**

1. Stop new deployments.
2. Revert the branch to the last passing phase.
3. Deploy the prior version.
4. **Investigate** what failed (do not re-attempt without root cause).

**After P2.0 (multi-version system):** Rollback is more complex; feature flags and gradual deployment become necessary.

---

## Success criteria

When all of the above is complete:

```bash
# All CI jobs green
github-check-status acx-city main  # → all green

# All tests green
(cd backend && pytest -q) && echo "PASS"
(cd frontend && npm run build) && echo "PASS"
(cd dashboard && npx next build) && echo "PASS"

# All exit gates pass (see each phase)
for phase in P0.0 P0.1 P0.2 P0.3 P0.4 P0.5; do
  verify_gate_$phase || echo "FAIL: $phase"
done

# Capability matrix all-Yes
grep "^| .*| Yes | Yes | Yes | Yes | Yes | Yes | Yes |" docs/CAPABILITY_MATRIX.md | wc -l
# Expected: at least 10 (all of P0)
```

The plan is done when:

1. **Every feature in the capability matrix is all-Yes or explicitly out of scope.**
2. **Every commit to `main` passes all three CI jobs.**
3. **The repository has never had a release-blocking commit in the last 60 days.**
4. **The golden-path test has run 50 consecutive times without failure.**

---

## Document updates during execution

Keep these files in sync as work progresses:

| File | When to update |
|---|---|
| `docs/CAPABILITY_MATRIX.md` | After each phase; flip capabilities to Yes |
| `AGENTS.md` | After P1.2 (multi-agent convergence); describe the real pipeline |
| `README.md` | After P0.1 (disable main.yml); after P1.8 (liveness/readiness); after P3 (Celery decision) |
| `FOUNDATION_PHASE.md` | After P0.8 (golden-path); describe what works |

---

## Estimated timeline

| Phase | Effort | Cumulative |
|---|---|---|
| P0.0 (green builds) | 1–2 days | 1–2 days |
| P0.1 (freeze + matrix) | 0.5 days | 1.5–2.5 days |
| P0.2 (durable chapters) | 3–4 days | 4.5–6.5 days |
| P0.3 (one API) | 4–5 days | 8.5–11.5 days |
| P0.4 (contract layer) | 2–3 days | 10.5–14.5 days |
| P0.5 (lease + heartbeat) | 2–3 days | 12.5–17.5 days |
| P0.6 (stages + idempotent) | 3–4 days | 15.5–21.5 days |
| P0.7 (FakeSpeechProvider) | 1–2 days | 16.5–23.5 days |
| P0.8 (golden-path E2E) | 2–3 days | 18.5–26.5 days |

**P0 total: ~4–5 weeks for one engineer, or 2 weeks for a pair.**

P1 phases (P1.1–P1.8) follow and are more parallel; estimate another 4–6 weeks.

P2 and P3 are optional/measurement-driven, another 2–4 weeks if pursued.

**Grand total: 10–15 weeks to full capability.**

