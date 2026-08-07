# Disaster Recovery & Business Continuity Plan

> **Owner:** Platform Engineering  
> **Last Updated:** 2026-08-07  
> **Review Cadence:** Quarterly  
> **Classification:** Internal — Confidential

---

## Table of Contents

1. [RTO / RPO Targets](#1-rtro--rpo-targets)
2. [Backup Schedule](#2-backup-schedule)
3. [GPU Worker Recovery Procedure](#3-gpu-worker-recovery-procedure)
4. [Runbook: Failure Scenarios](#4-runbook-failure-scenarios)
5. [Incident Response Checklist](#5-incident-response-checklist)
6. [Communication Templates](#6-communication-templates)
7. [Testing & Drills](#7-testing--drills)

---

## 1. RTO / RPO Targets

| Service | RTO (Recovery Time Objective) | RPO (Recovery Point Objective) | Notes |
|---|---|---|---|
| **API Gateway** | 5 min | 0 (stateless) | Failover to standby region via Vercel |
| **PostgreSQL** | 15 min | 5 min (PITR WAL archival) | Automated failover + manual restore |
| **Redis** | 10 min | 0 (ephemeral cache) | Rebuild from source of truth on failure |
| **GPU Workers** | 20 min | Checkpoint-level (~5 min) | Chapter-level resume; orphan sweeper active |
| **R2 Object Storage** | None | 0 (versioned) | Multi-region; no single point of failure |
| **Vercel (Frontend/Edge)** | 5 min | 0 (deployed artifact) | Automatic rollback to last healthy deploy |

> **RTO** = maximum acceptable downtime.  
> **RPO** = maximum acceptable data loss measured in time.

---

## 2. Backup Schedule

### 2.1 PostgreSQL

| Backup Type | Schedule | Retention | Storage |
|---|---|---|---|
| **WAL Archiving (PITR)** | Continuous | 7 days | R2 `acx-pg-wal/` |
| **pg_dump (full)** | Daily 03:00 UTC | 30 days | R2 `acx-pg-dump/` |
| **pg_dump (full)** | Weekly Sunday 03:00 UTC | 90 days | R2 `acx-pg-dump-weekly/` |

```bash
# Manual backup trigger (emergency)
pg_dump -Fc -Z9 -f /tmp/acx_$(date +%Y%m%d_%H%M%S).dump acx_prod

# Upload to R2
r2 upload /tmp/acx_*.dump acx-pg-dump/
```

### 2.2 R2 Object Storage

- **Versioning:** Enabled on all buckets (`acx-audio`, `acx-covers`, `acx-exports`)
- **Lifecycle rules:**
  - Non-current versions retained for 30 days
  - Expired object delete markers cleaned after 7 days
- **Cross-region replication:** Primary `us-east-1` → Failover `eu-west-1`

### 2.3 Audio File Retention

| Type | Retention Period | Notes |
|---|---|---|
| Generated chapter audio | 90 days | After project completion |
| Preview/sample clips | 30 days | Ephemeral cache |
| Source TTS raw output | 7 days | Re-generable; stored transiently |
| Final merged audiobook | Indefinite | Customer deliverable |

### 2.4 Redis

- **No persistent backups.** Redis is used as a volatile cache and task queue.
- On failure, Redis is rebuilt by:
  1. API cold-start populates session cache
  2. Job queue rebuilds from PostgreSQL `jobs` table
  3. Rate-limiter counters reset (acceptable)

---

## 3. GPU Worker Recovery Procedure

### 3.1 Orphan Sweeper

Orphaned tasks occur when a GPU worker crashes mid-job without sending a completion signal.

```sql
-- Orphan sweeper runs every 60 seconds
-- Finds tasks stuck in 'processing' for > 10 minutes with no heartbeat
UPDATE jobs
SET status = 'queued',
    worker_id = NULL,
    retry_count = retry_count + 1,
    updated_at = NOW()
WHERE status = 'processing'
  AND updated_at < NOW() - INTERVAL '10 minutes'
  AND retry_count < max_retries;
```

**Configuration:**

| Parameter | Value | Description |
|---|---|---|
| `sweeper_interval` | 60s | How often orphan sweeper runs |
| `heartbeat_timeout` | 10 min | Time without heartbeat before task is orphaned |
| `max_retries` | 3 | Max re-queue attempts before human escalation |

### 3.2 Checkpoint Resume

GPU workers write checkpoints to R2 every chapter boundary:

```
s3://acx-checkpoints/{project_id}/{chapter_id}/checkpoint.json
```

**Checkpoint schema:**

```json
{
  "project_id": "uuid",
  "chapter_id": "uuid",
  "paragraph_index": 142,
  "voice_config": { "voice_id": "edge-en-us-1", "speed": 1.0 },
  "audio_segments": ["seg_001.wav", "seg_002.wav", "..."],
  "timestamp": "2026-08-07T06:00:00Z"
}
```

**Resume flow:**

1. Worker picks up re-queued job from Redis/PostgreSQL
2. Checks R2 for existing checkpoint for that chapter
3. If checkpoint exists:
   - Skips completed paragraphs (`paragraph_index` onwards)
   - Reuses already-generated audio segments
4. If no checkpoint: starts from beginning

### 3.3 Chapter-Level Resume

Since checkpoints are per-chapter, the **minimum resume unit is one chapter.** This means:

- A worker crash at paragraph 80 of 100 in a chapter re-does that entire chapter
- Adjacent chapters are unaffected
- The orchestrator tracks chapter-level completion in PostgreSQL

```sql
SELECT id, chapter_number, status
FROM chapters
WHERE project_id = $1
ORDER BY chapter_number;
-- Possible statuses: pending, processing, completed, failed
```

---

## 4. Runbook: Failure Scenarios

### 4.1 API Gateway Down

**Detection:** Vercel status page alert, uptime monitor, or user reports  
**RTO:** 5 minutes

**Steps:**

1. Check [Vercel Status](https://www.vercel-status.com/) for platform incidents
2. If Vercel platform issue → wait; no action needed (Vercel's SLO applies)
3. If deployment-related:
   ```bash
   # Rollback to last healthy deployment
   vercel rollback --token=$VERCEL_TOKEN
   ```
4. If custom domain issue:
   ```bash
   # Verify DNS resolution
   dig api.acx.city +short
   # Check SSL certificate
   openssl s_client -connect api.acx.city:443 -servername api.acx.city
   ```
5. Notify stakeholders via status page update (see §6)

### 4.2 PostgreSQL Failure

**Detection:** Connection pool errors, health check failures  
**RTO:** 15 minutes

**Steps:**

1. Verify failure is not network-related:
   ```bash
   pg_isready -h $PG_HOST -p 5432 -U acx
   ```
2. Check Supabase/managed provider dashboard for maintenance or outages
3. **If primary is down and failover available:**
   - Managed failover triggers automatically (Supabase)
   - Verify DNS CNAME resolves to new primary
   ```bash
   psql $DATABASE_URL -c "SELECT pg_is_in_recovery();"
   -- Should return 'f' (false) on primary
   ```
4. **If manual restore needed (PITR):**
   ```bash
   # Stop application connections
   # Restore from latest WAL + base backup
   pg_basebackup -h $PG_BACKUP_HOST -D /data/pg_restore -Fp -Xs -P
   
   # Replay WAL to point of failure
   # Configure recovery.conf / postgresql.conf:
   #   restore_command = 'r2 get acx-pg-wal/%f %p'
   #   recovery_target_time = '2026-08-07 05:55:00+00'
   
   pg_ctl start -D /data/pg_restore
   ```
5. Verify data integrity:
   ```sql
   SELECT count(*) FROM projects;
   SELECT count(*) FROM chapters WHERE status = 'completed';
   ```
6. Resume GPU workers (see §3)

### 4.3 Redis Failure

**Detection:** Cache miss spike, queue processing halt  
**RTO:** 10 minutes

**Steps:**

1. Verify Redis is unreachable:
   ```bash
   redis-cli -h $REDIS_HOST ping
   ```
2. Restart Redis:
   ```bash
   redis-cli shutdown nosave
   systemctl restart redis
   ```
3. If data corruption:
   ```bash
   # Wipe and restart fresh
   redis-cli FLUSHALL
   systemctl restart redis
   ```
4. Verify application reconnection:
   ```bash
   curl -s http://localhost:3000/health | jq '.redis'
   ```
5. Monitor queue rebuild from PostgreSQL:
   ```sql
   SELECT status, count(*) FROM jobs GROUP BY status;
   ```

### 4.4 GPU Worker Failure

**Detection:** Job queue depth increasing, orphan sweeper alerts  
**RTO:** 20 minutes

**Steps:**

1. Identify failed worker:
   ```bash
   # Check worker health endpoints
   for w in gpu-1 gpu-2 gpu-3; do
     curl -sf "http://$w:8080/health" || echo "$w: DOWN"
   done
   ```
2. Check for orphaned tasks (automatic via sweeper, but manual verification):
   ```sql
   SELECT id, project_id, chapter_id, worker_id, updated_at
   FROM jobs
   WHERE status = 'processing'
     AND updated_at < NOW() - INTERVAL '10 minutes';
   ```
3. Restart failed worker:
   ```bash
   ssh gpu-N "sudo systemctl restart acx-worker"
   ```
4. If hardware failure:
   ```bash
   # Scale up replacement worker
   kubectl scale deployment/acx-gpu-worker --replicas=4
   ```
5. Verify checkpoint resume is working:
   ```bash
   # Check recent checkpoint activity
   r2 ls acx-checkpoints/ --recursive | tail -20
   ```
6. Monitor queue drain rate to confirm recovery

### 4.5 R2 Object Storage Failure

**Detection:** Upload/download failures, S3-compatible API errors  
**RTO:** N/A (Cloudflare SLA applies)

**Steps:**

1. Check [Cloudflare Status](https://www.cloudflarestatus.com/) for R2 incidents
2. Verify bucket access:
   ```bash
   r2 ls acx-audio/ | head -5
   ```
3. If regional failure: verify cross-region replication is serving reads
4. If account-level issue: escalate to Cloudflare support immediately
5. **Workaround:** Cache recent audio files in local NVMe for playback continuity

### 4.6 Vercel Platform Failure

**Detection:** Deployment failures, edge function errors  
**RTO:** 5 minutes

**Steps:**

1. Check Vercel status page
2. If build/deploy failures: retry deployment
   ```bash
   vercel deploy --prod --token=$VERCEL_TOKEN
   ```
3. If edge function failures: check function logs
   ```bash
   vercel logs acx-city --token=$VERCEL_TOKEN
   ```
4. Fallback: serve static build from alternative CDN (Cloudflare Pages mirror)

---

## 5. Incident Response Checklist

Use this checklist for any production incident:

### Phase 1: Detection & Triage (0–5 min)

- [ ] **Acknowledge** the alert / incident report
- [ ] **Assess severity** using the table below
- [ ] **Create incident channel** (`#incident-YYYYMMDD-HHMM`)
- [ ] **Assign Incident Commander (IC)**

| Severity | Criteria | Response Time |
|---|---|---|
| **SEV-1** | Full service outage, data loss risk | Immediate |
| **SEV-2** | Partial outage, degraded performance | 15 min |
| **SEV-3** | Non-critical feature failure, workaround exists | 1 hour |
| **SEV-4** | Cosmetic / low-impact issue | Next business day |

### Phase 2: Investigation (5–30 min)

- [ ] **Identify scope:** Which services / users are affected?
- [ ] **Check dashboards:** Grafana, Vercel Analytics, Supabase Dashboard
- [ ] **Review recent deployments:**
  ```bash
  git log --oneline -10
  vercel ls --token=$VERCEL_TOKEN
  ```
- [ ] **Check external dependencies:** Cloudflare, Supabase, ElevenLabs, etc.
- [ ] **Determine root cause** or narrow down to subsystem

### Phase 3: Mitigation (concurrent with Phase 2)

- [ ] **Rollback** if recent deployment is the cause
- [ ] **Scale up** if resource exhaustion
- [ ] **Failover** if infrastructure component is down
- [ ] **Enable rate limiting** if abuse / traffic spike
- [ ] **Communicate** to users (see §6)

### Phase 4: Resolution & Recovery

- [ ] **Implement fix** (hotfix or infrastructure change)
- [ ] **Verify recovery** via health checks and manual testing
- [ ] **Resume normal operations** (re-enable features, remove rate limits)
- [ ] **Update status page** to "Resolved"

### Phase 5: Post-Incident

- [ ] **Write post-mortem** within 48 hours
- [ ] **Schedule blameless retrospective** within 1 week
- [ ] **File follow-up tickets** for preventive measures
- [ ] **Update this runbook** with lessons learned

---

## 6. Communication Templates

### 6.1 Internal: Incident Start

```
🚨 INCIDENT DECLARED — [SEV-X]

Service: [affected service]
Impact: [brief description]
IC: @[name]
Channel: #incident-YYYYMMDD-HHMM
Status: Investigating

Next update in 15 minutes.
```

### 6.2 Internal: Status Update

```
📋 INCIDENT UPDATE — [SEV-X] — [HH:MM UTC]

Current status: [Investigating / Identified / Fixing / Monitoring]
What we know: [1-2 sentences]
What we're doing: [current action]
ETA to resolution: [estimate or "unknown"]

Next update in [15/30/60] minutes.
```

### 6.3 Internal: Resolution

```
✅ INCIDENT RESOLVED — [SEV-X] — [HH:MM UTC]

Duration: [X minutes/hours]
Root cause: [brief summary]
Impact: [affected users/requests]
Fix applied: [what was done]

Post-mortem scheduled for [date]. Thread in #incident-YYYYMMDD-HHMM.
```

### 6.4 External: Status Page (Degraded)

```markdown
**[Service Name] — Degraded Performance**

We are currently experiencing [brief description of issue]. 
Some users may experience [specific symptom].

Our team is actively working on a resolution. 
We will provide another update within [30 minutes / 1 hour].

**Affected components:**
- [ ] API
- [ ] Audio Generation
- [ ] Dashboard
- [ ] File Uploads
```

### 6.5 External: Status Page (Resolved)

```markdown
**[Service Name] — Service Restored**

The issue affecting [brief description] has been resolved as of [HH:MM UTC].

**What happened:** [1-2 sentences, non-technical]
**Duration:** [X minutes/hours]
**Preventive measures:** [what we're doing to prevent recurrence]

We apologize for the inconvenience and appreciate your patience.
```

### 6.6 External: Email to Affected Users

```
Subject: ACX City Service Disruption — [Date]

Hi [Name],

We experienced a service disruption on [date] between [start] and [end] (UTC) 
that affected [specific feature/service].

What happened: [plain-language explanation]
What we did: [resolution steps in plain language]
What we're doing: [preventive measures]

If you were processing an audiobook during this time, your project has been 
[automatically resumed / requires your attention — here's how to check: link].

We take reliability seriously and are implementing [specific improvement] to 
prevent this from recurring.

If you have questions, reply to this email or contact support@acx.city.

Best regards,
The ACX City Team
```

---

## 7. Testing & Drills

### 7.1 Disaster Recovery Drills

| Drill | Frequency | Scope |
|---|---|---|
| PostgreSQL PITR restore test | Quarterly | Restore to staging, verify data integrity |
| GPU worker crash simulation | Quarterly | Kill random worker, verify orphan sweep + resume |
| Full region failover | Biannually | Switch DNS, verify all services in failover region |
| Backup restoration audit | Monthly | Verify backups are restorable (don't deploy, just test) |
| Incident response tabletop | Quarterly | Walk through hypothetical scenarios with team |

### 7.2 Drill Checklist

- [ ] Schedule drill window (off-peak hours)
- [ ] Notify on-call team
- [ ] Execute drill procedure
- [ ] Measure actual RTO/RPO vs targets
- [ ] Document results and gaps
- [ ] File improvement tickets
- [ ] Update this plan

### 7.3 Automated Backup Verification

```bash
#!/usr/bin/env bash
# verify-backups.sh — runs daily via cron at 06:00 UTC
# Verifies latest pg_dump is restorable

set -euo pipefail

LATEST_DUMP=$(r2 ls acx-pg-dump/ --sort-by lastmodified | tail -1 | awk '{print $NF}')
DUMP_AGE=$(r2 stat "acx-pg-dump/$LATEST_DUMP" | grep LastModified)

# Verify dump age < 36 hours
if [ ... ]; then
  echo "✅ Backup is fresh: $LATEST_DUMP"
else
  echo "❌ STALE BACKUP: $LATEST_DUMP" | mail -s "CRITICAL: Stale PostgreSQL Backup" ops@acx.city
fi

# Test restore to ephemeral instance
pg_restore --list "r2://acx-pg-dump/$LATEST_DUMP" > /dev/null 2>&1 && \
  echo "✅ Dump is valid" || \
  echo "❌ CORRUPT DUMP" | mail -s "CRITICAL: Corrupt PostgreSQL Backup" ops@acx.city
```

---

## Appendix: Key Contacts

| Role | Name | Contact | Escalation |
|---|---|---|---|
| On-Call Engineer | [Rotation] | PagerDuty | Primary |
| Platform Lead | [Name] | [Phone/Slack] | Secondary |
| CTO | [Name] | [Phone] | SEV-1 only |
| Cloudflare Support | — | Enterprise ticket | R2/CDN issues |
| Supabase Support | — | Enterprise ticket | PostgreSQL issues |
| Vercel Support | — | Enterprise ticket | Deployment/Edge issues |

---

*This document should be reviewed and updated quarterly, or immediately after any SEV-1/SEV-2 incident.*
