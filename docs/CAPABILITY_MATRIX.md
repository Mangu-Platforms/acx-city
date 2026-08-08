# ACX City Capability Matrix

This matrix is the release gate for ACX City. A feature cannot ship until its row reads all-Yes. Updated as each phase completes.

**Column definitions:**
- **UI** — a user-reachable control exists in `frontend/`
- **API** — an endpoint exists on the canonical Flask `/api` surface and returns a valid response
- **Exec** — the code path runs in the deployed production topology (Flask + `worker.py`). Celery/FastAPI paths score **No**
- **Durable** — result survives a container replacement (object storage or Postgres, not local disk)
- **Resume** — a worker kill mid-operation resumes without duplicate paid synthesis
- **E2E** — an automated test exercises the full path from API to persisted output
- **Ship** — all of the above are Yes

| Capability | UI | API | Exec | Durable | Resume | E2E | Ship | Evidence |
|---|---|---|---|---|---|---|---|---|
| Signup / login | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:193-235`; `tests/test_api.py` |
| Upload manuscript | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:252` |
| Generate audiobook (single voice) | Yes | Yes | Yes | Partial | Partial | Partial | **No** | `jobs/pipeline.py`; chapter audio local-disk only (P0.2) |
| Chapter progress / resume | — | Yes | Yes | Partial | Partial | Yes | **No** | `ChapterResult` persists state but not the artifact (P0.2) |
| MP3 export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `storage.put_file` |
| M4B export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `_audio.export_m4b` |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:409`; `tests/test_jobs.py` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:433,446`; `tests/test_qc_gate.py` |
| Usage / quota ledger | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `UsageEvent`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:460`; `tests/test_download.py` |
| Character detection | Yes | `/v1` | **No** | Partial | No | **No** | **No** | `v1_api.py:275`; Celery not deployed |
| Character voice assignment | Yes | `/v1` | **No** | Yes | No | **No** | **No** | `v1_api.py:302`; `CharacterVoiceMap` |
| Pronunciation lexicon | Yes | `/v1` | **No** | Yes | No | **No** | **No** | `v1_api.py:342-397` |
| Multi-agent pipeline | Partial | `/v1` | Flag-gated | Partial | No | **No** | **No** | `PIPELINE_ENABLED` default `false` |
| Voice preview | Yes | **Broken** | **No** | No | No | **No** | **No** | Async/sync mismatch; wrong storage method names |
| Chapter streaming | Partial | **Broken** | **No** | No | No | **No** | **No** | `JobStatus.completed` does not exist; `ProviderRegistry` has no `first_available` |
| Waveform | Partial | **Broken** | **No** | No | No | **No** | **No** | Wrong column `duration_seconds`; stub returning `peaks: []` |
| Single-chapter rerender | Partial | **Broken** | **No** | No | No | **No** | **No** | Sends whole book as chapter text; Celery not deployed |
| Voice cloning | Yes | **501** | **No** | No | No | **No** | **No** | `v1_api.py:567` raises `501` |
| EPUB export (from job) | Partial | **Broken** | **No** | No | No | **No** | **No** | Wrong ORM attrs; no `text_content` column |
| EPUB export (client-supplied) | Partial | Partial | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:618`; 5 tests now passing (fixed P0.0) |

¹ Functionally sound — scores **No** only because the product was not building before P0.0. Flip to Yes after P0.8 golden-path E2E.

## Phase tracker

| Phase | Scope | Status | Date |
|---|---|---|---|
| **P0.0** | Get `main` green | ✅ Complete | 2026-08-08 |
| **P0.1** | Freeze expansion + capability matrix + disable autonomous workflow | ✅ Complete | 2026-08-08 |
| **P0.2** | Durable chapter artifacts | pending | — |
| **P0.3** | One Flask `/api` surface (remove `/v1`) | pending | — |
| **P0.4** | Contract layer + generated TS types | pending | — |
| **P0.5** | Lease + heartbeat + orphan recovery | pending | — |
| **P0.6** | Stage checkpoints + idempotent synthesis | pending | — |
| **P0.7** | `FakeSpeechProvider` | pending | — |
| **P0.8** | Golden-path E2E test in CI | pending | — |
