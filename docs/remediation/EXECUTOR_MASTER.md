# ACX City Remediation — Master Executor

**For:** Claude Code or autonomous agent running in a single long session.

**Goal:** Execute all of P0.0–P0.8 (the "zero-to-golden-path" program) in one session, with resumability.

**How to use this:** Follow the manifest below. After each phase, the exit gate must pass. If interrupted, resume at the next uncompleted phase. State is tracked in `.remediation-state` (Git-ignored JSON).

---

## Manifest

Each phase is **atomic** — it either completes and commits, or rolls back and stays at the prior phase.

| Phase | Scope | Est. time | Status |
|---|---|---|---|
| **P0.0** | Get `main` green | 1–2 hrs | `pending` |
| **P0.1** | Freeze + matrix + disable workflow | 30 min | `pending` |
| **P0.2** | Durable chapter artifacts | 2–3 hrs | `pending` |
| **P0.3** | One Flask `/api` surface | 3–4 hrs | `pending` |
| **P0.4** | Contract layer + TS codegen | 1–2 hrs | `pending` |
| **P0.5** | Lease + heartbeat + orphan recovery | 2–3 hrs | `pending` |
| **P0.6** | Stage checkpoints + idempotent synthesis | 2–3 hrs | `pending` |
| **P0.7** | `FakeSpeechProvider` | 1 hr | `pending` |
| **P0.8** | Golden-path E2E test | 2–3 hrs | `pending` |

---

## P0.0: Get `main` green (1–2 hours)

### Objective
All three CI jobs must exit 0: `pytest -q`, `npm run build`, `npx next build`.

### Prerequisites
- Repo cloned to `/tmp/acx-city` or similar.
- Python 3.11+, Node 20+, npm, git.
- Write access to the repository.

### Tasks

#### 0.0.1 — Fix frontend App.tsx (TypeScript errors)

**What:** Two missing fields/types in `frontend/src/App.tsx`.

**Changes:**

1. **Line 131** — Add missing field to `StockVoice` typedef or remove the call.
   - Inspect: `grep -n "provider_voice_id" frontend/src/App.tsx`
   - Inspect: `grep -n "interface StockVoice\|type StockVoice" frontend/src/types/*.ts`
   - **Option A** (recommended): Remove `.provider_voice_id` from the call at line 131.
     ```typescript
     // BEFORE:
     setSelectedVoice(v.provider_voice_id || '')
     // AFTER:
     setSelectedVoice(v.id)
     ```
   - **Option B**: Add the field to `StockVoice` typedef if it belongs there.
   - **Verify:** `cd frontend && npx tsc --noEmit 2>&1 | grep -c "provider_voice_id"` → should be 0.

2. **Line 170** — Fix `Workspace` type to include "characters", "lexicon", "production".
   - Inspect: `grep -n "type Workspace\|type Page" frontend/src/App.tsx`
   - **Change:**
     ```typescript
     // BEFORE:
     type Workspace = 'upload' | 'production' | 'settings'
     
     // AFTER:
     type Workspace = 'upload' | 'production' | 'settings' | 'characters' | 'lexicon'
     ```
   - **Verify:** `cd frontend && npx tsc --noEmit 2>&1 | tail -1` → should show 0 errors.

#### 0.0.2 — Fix dashboard (missing directive, import path, dependency)

**What:** Three fixes in one file: `dashboard/app/dashboard/pipeline/page.tsx`.

**Changes:**

1. **Line 1** — Add `'use client'` directive.
   ```typescript
   // ADD at the very top:
   'use client'
   
   import React, { useEffect, useState, useCallback } from 'react'
   ```

2. **Line 2** — Fix import path.
   ```typescript
   // BEFORE:
   import { api } from '../../lib/api'
   
   // AFTER:
   import { api } from '../../../lib/api'
   ```

3. **Add `lucide-react` to `dashboard/package.json`:**
   ```json
   "dependencies": {
     "lucide-react": "^0.263.1",  // match version from frontend if possible
     ...
   }
   ```
   Then run: `cd dashboard && npm install`

4. **Line 37** — Add type to `res` parameter.
   ```typescript
   // BEFORE:
   const res = await api.get(`/api/jobs`)
   
   // AFTER:
   const res = await api.get(`/api/jobs`) as { data?: any }
   ```

5. **Line 41** — Fix the unknown type access.
   ```typescript
   // BEFORE:
   const uniqueProjects = [...new Map(jobs.map(j => [j.project_id, j])).values()]
   
   // AFTER:
   const uniqueProjects = [...new Map((res.data as any)?.jobs?.map((j: any) => [j.project_id, j]) || []).values()]
   ```

**Verify:**
```bash
cd dashboard
npm install --silent
npx tsc --noEmit 2>&1 | grep -c "error TS"  # Should be 0
npx next build 2>&1 | tail -5  # Should say "route (pages)" and exit cleanly
```

#### 0.0.3 — Fix backend EPUB generator

**What:** `EpubBook` has no `.chapters` attribute in `ebooklib==0.18`.

**File:** `backend/services/epub_generator.py:92`

**Change:**

```python
# BEFORE:
chapter_num = len(self.book.chapters) + 1

# AFTER:
html_chapters = [item for item in self.book.items if isinstance(item, epub.EpubHtml)]
chapter_num = len(html_chapters) + 1
```

**Verify:**
```bash
cd backend
export JWT_SECRET=ci-test
pytest tests/test_epub_generator.py -q 2>&1 | tail -1  # Should say "passed" not "failed"
```

### Exit gate (all must pass)

```bash
cd /tmp/acx-city

# 1. Backend tests
(cd backend && export JWT_SECRET=test && pytest -q 2>&1 | tail -1 | grep -E "passed|failed")
# Expected: contains "passed" and "119" or more

# 2. Frontend build
(cd frontend && npm run build 2>&1 | tail -1)
# Expected: exit code 0

# 3. Dashboard build
(cd dashboard && npx next build 2>&1 | grep -i "failed\|error" && echo "FAIL" || echo "PASS")
# Expected: exit code 0, no "failed"
```

**When all three pass, update state:**

```bash
echo '{"phase": "P0.0", "status": "completed"}' > .remediation-state
git add -A && git commit -m "P0.0: Get main green"
```

---

## P0.1: Freeze expansion + matrix + disable workflow (30 min)

### Objective
1. Publish `docs/CAPABILITY_MATRIX.md`.
2. Add branch protection rule (GitHub UI).
3. Disable `.github/workflows/main.yml`.
4. Document why in `README.md`.

### Tasks

#### 1.0.1 — Add CAPABILITY_MATRIX.md

**File:** `docs/CAPABILITY_MATRIX.md` (new)

```markdown
# ACX City Capability Matrix

This matrix is the release gate for ACX City. A feature cannot ship until its row reads all-Yes.

Updated as each phase completes.

| Capability | UI | API | Exec | Durable | Resume | E2E | Ship |
|---|---|---|---|---|---|---|---|
| Signup / login | Yes | Yes | Yes | Yes | n/a | Partial | **No** |
| ... [copy the full table from the Remediation Plan § 3] ...
```

#### 1.0.2 — Disable main.yml

```bash
cd /tmp/acx-city

# Rename the workflow
mkdir -p .github/disabled
mv .github/workflows/main.yml .github/disabled/main.yml.disabled

# Add a note to README.md
cat >> README.md << 'EOF'

## Autonomous Workflow

The daily multi-agent workflow (`.github/disabled/main.yml.disabled`) has been disabled as of this remediation. It generated unreviewable churn against a non-building codebase. It may be reconsidered after P1.8 (dashboard rebuild) if measurement justifies it.
EOF
```

#### 1.0.3 — Set branch protection (GitHub UI)

**Manual step (cannot automate):**

1. Go to repository Settings → Branches.
2. Add rule for `main`.
3. Require status checks: `backend`, `frontend`, `dashboard` (from `ci.yml`).
4. Require branches up to date before merge.

**Verification (after the manual step):**

```bash
# Verify the workflow is gone
test ! -f .github/workflows/main.yml && echo "PASS: main.yml removed"

# Verify the disabled copy exists
test -f .github/disabled/main.yml.disabled && echo "PASS: backup exists"

# Verify README is updated
grep -c "Autonomous Workflow" README.md | grep -E "[1-9]" && echo "PASS: README updated"
```

### Exit gate

```bash
# 1. Matrix exists
test -f docs/CAPABILITY_MATRIX.md && wc -l docs/CAPABILITY_MATRIX.md | grep -E "[0-9]" && echo "PASS"

# 2. main.yml disabled
test ! -f .github/workflows/main.yml && echo "PASS: deleted"
test -f .github/disabled/main.yml.disabled && echo "PASS: backup"

# 3. README updated
grep "Autonomous Workflow" README.md && echo "PASS: documented"
```

**When all pass, commit:**

```bash
git add -A && git commit -m "P0.1: Freeze expansion, publish capability matrix, disable main.yml"
echo '{"phase": "P0.1", "status": "completed"}' > .remediation-state
```

---

## P0.2: Durable chapter artifacts (2–3 hours)

### Objective
Chapters upload to object storage with checksums. Resume doesn't re-synthesize.

### Tasks

#### 2.0.1 — Create migration

**File:** `backend/migrations/versions/<timestamp>_add_chapter_storage.py`

```python
"""Add durable chapter artifacts."""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('chapter_results', sa.Column('audio_key', sa.String(512), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_sha256', sa.String(64), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_bytes', sa.Integer, nullable=True))
    op.add_column('chapter_results', sa.Column('content_type', sa.String(100), nullable=True))
    op.add_column('chapter_results', sa.Column('synthesis_id', sa.String(64), nullable=True))
    op.create_index('ix_chapter_synthesis', 'chapter_results', ['synthesis_id'])

def downgrade():
    op.drop_index('ix_chapter_synthesis', 'chapter_results')
    op.drop_column('chapter_results', 'synthesis_id')
    op.drop_column('chapter_results', 'content_type')
    op.drop_column('chapter_results', 'audio_bytes')
    op.drop_column('chapter_results', 'audio_sha256')
    op.drop_column('chapter_results', 'audio_key')
```

**Apply:**

```bash
cd backend
alembic upgrade head
# Verify columns exist:
python -c "from db.models import ChapterResult; print([c.name for c in ChapterResult.__table__.columns if 'audio' in c.name])"
```

#### 2.0.2 — Update ChapterResult model

**File:** `backend/db/models.py` → add to `ChapterResult` class:

```python
audio_key: Mapped[Optional[str]] = mapped_column(String(512))
audio_sha256: Mapped[Optional[str]] = mapped_column(String(64))
audio_bytes: Mapped[Optional[int]] = mapped_column(Integer)
content_type: Mapped[Optional[str]] = mapped_column(String(100))
synthesis_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
```

#### 2.0.3 — Add upload helper in pipeline.py

**File:** `backend/jobs/pipeline.py` → add function before `run_job()`:

```python
def _upload_chapter_audio(session: Session, job: Job, chapter_row: ChapterResult,
                          chapter_index: int, audio_path: str) -> str:
    """Upload chapter audio to storage and record metadata. Returns the storage key."""
    import hashlib
    storage = get_storage()
    
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Chapter audio not found: {audio_path}")
    
    with open(audio_path, 'rb') as f:
        audio_bytes = f.read()
    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    
    qc = _audio.qc_check(audio_path)
    if not qc.get('duration_s'):
        raise ValueError(f"Chapter {chapter_index}: audio has no decodable duration")
    
    key = _output_key(job, f"chapters/{chapter_index:03d}.mp3")
    storage.put_bytes(key, audio_bytes, content_type="audio/mpeg")
    
    chapter_row.audio_key = key
    chapter_row.audio_sha256 = audio_sha256
    chapter_row.audio_bytes = len(audio_bytes)
    chapter_row.content_type = "audio/mpeg"
    
    return key
```

#### 2.0.4 — Update resume logic in run_job()

**File:** `backend/jobs/pipeline.py` → replace the resume check:

```python
# OLD (around line 150):
if row.status == ChapterStatus.done:
    path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
    if os.path.exists(path):
        chapter_files.append(path); chapter_titles.append(chapter["title"]); continue

# NEW:
if row.status == ChapterStatus.done:
    if row.audio_key:
        try:
            audio_bytes = storage.get_bytes(row.audio_key)
            if hashlib.sha256(audio_bytes).hexdigest() == row.audio_sha256:
                path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
                with open(path, 'wb') as f:
                    f.write(audio_bytes)
                chapter_files.append(path)
                chapter_titles.append(chapter["title"])
                continue
        except Exception as e:
            log.warning(f"Failed to fetch chapter {i} from storage: {e}")
    
    path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
    if os.path.exists(path):
        chapter_files.append(path); chapter_titles.append(chapter["title"]); continue
```

#### 2.0.5 — Add upload call after chapter assembly

**File:** `backend/jobs/pipeline.py` → after the `session.commit()` at the end of the chapter loop:

```python
        job.progress = int(10 + (i + 1) * progress_per_chapter)
        job.updated_at = utcnow()
        session.commit()  # durable per-chapter checkpoint
        
        # NEW: Upload to storage
        try:
            _upload_chapter_audio(session, job, row, i, chapter_path)
            session.commit()
        except Exception as e:
            log.error(f"Failed to upload chapter {i}: {e}; will retry on next run")
            row.status = ChapterStatus.pending
            row.audio_key = None
            session.commit()
```

### Exit gate

```bash
cd backend
export JWT_SECRET=test

# 1. Migration applied
alembic current | grep -i "add_chapter_storage" && echo "PASS: migration applied"

# 2. Model loads
python -c "from db.models import ChapterResult; assert hasattr(ChapterResult, 'audio_key')" && echo "PASS: model updated"

# 3. Tests pass (if they exist for this)
pytest tests/test_jobs.py -q 2>&1 | grep -E "passed|failed"
```

**Commit:**

```bash
git add -A && git commit -m "P0.2: Add durable chapter artifacts (storage keys, checksums)"
echo '{"phase": "P0.2", "status": "completed"}' > .remediation-state
```

---

## P0.3–P0.8: Continuation template

For each remaining phase (P0.3–P0.8), follow the same pattern:

1. **Task breakdown** — exact files and line ranges.
2. **Code blocks** to insert/replace.
3. **Exit gate** — machine-checkable (bash command with clear pass/fail).
4. **Commit** when complete.

For full detail on P0.3–P0.8, refer to the **Implementation Guide** document.

---

## Resumability

**State file:** `.remediation-state` (git-ignored)

```json
{
  "phase": "P0.2",
  "status": "completed",
  "timestamp": "2025-08-08T15:30:00Z"
}
```

**On resume:** Check `.remediation-state`. If `status: completed`, move to the next phase. If `in_progress`, re-run the exit gate; if it passes, move forward; if it fails, redo the phase.

**Rollback for a phase:** Git provides the safety net.

```bash
# If P0.2 fails exit gate:
git diff HEAD~1  # see what changed
git reset --hard HEAD~1  # revert
# Fix the issues in the implementation
# Re-attempt P0.2
```

---

## Timeline for full P0.0–P0.8 execution

| Phase | Time | Cumulative |
|---|---|---|
| P0.0 | 1–2 hrs | 1–2 hrs |
| P0.1 | 0.5 hrs | 1.5–2.5 hrs |
| P0.2 | 2–3 hrs | 3.5–5.5 hrs |
| P0.3 | 3–4 hrs | 6.5–9.5 hrs |
| P0.4 | 1–2 hrs | 7.5–11.5 hrs |
| P0.5 | 2–3 hrs | 9.5–14.5 hrs |
| P0.6 | 2–3 hrs | 11.5–17.5 hrs |
| P0.7 | 1 hr | 12.5–18.5 hrs |
| P0.8 | 2–3 hrs | 14.5–21.5 hrs |

**Single session:** ~18 hours (with breaks). Realistically, 2 business days for a skilled engineer, 1 day with pair programming.

---

## Success criteria

All three at the end:

```bash
pytest -q  # 119+ passed, 0 failed
npm run build  # exit 0
npx next build  # exit 0

# Capability matrix has at least 10 rows all-Yes
grep "| Yes | Yes | Yes | Yes | Yes | Yes | Yes |" docs/CAPABILITY_MATRIX.md | wc -l  # >= 10
```

When these hold, you have a **shippable P0**. The system is:
- **Building** on all three surfaces.
- **Crash-safe** (worker + job recovery).
- **One API** (no `/v1`).
- **Idempotent** (no duplicate synthesis).
- **E2E tested** (golden path in CI).

