# SOC 2 Type I Compliance Checklist — ACX City

> **Last updated:** 2026-08-07
> **Status:** In-progress (pre-audit gap analysis)
> **Auditor:** TBD
> **Target attestation date:** TBD

---

## 1. Access Controls (CC6)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 1.1 | Unique user identification for every human and service account | ✅ Built | `backend/auth/models.py` → `User` model with `user_id` (UUID), `email`, `auth_provider`. Every request carries a JWT with `sub` claim. |
| 1.2 | Multi-factor authentication (MFA) for privileged accounts | ✅ Built | `backend/auth/mfa.py` → TOTP enrollment & verification. Enforced for org admin and billing roles via `backend/auth/rbac.py:require_mfa()`. |
| 1.3 | Role-Based Access Control (RBAC) with least-privilege roles | ✅ Built | `backend/auth/rbac.py` → `Role` enum: `viewer`, `operator`, `admin`, `org_owner`. Permission matrix in `RBAC_MATRIX`. Enforced at FastAPI dependency layer (`Depends(require_role(...))`). |
| 1.4 | Organisation-level data isolation (tenant isolation) | ✅ Built | Every DB query is scoped by `org_id` via `backend/db/org_scoping.py:OrgScopedSession`. Row-Level Security policies on PostgreSQL tables (`alembic/migrations/002_rls_policies.sql`). |
| 1.5 | Session management: idle timeout, absolute timeout, forced logout | ✅ Built | JWT expiry: 15 min (access), 7 days (refresh). Idle timeout enforced via `backend/auth/session.py:check_idle_timeout()`. Admin can revoke sessions via `/api/v1/admin/sessions/revoke`. |
| 1.6 | Automated provisioning & de-provisioning (SCIM / SAML) | 🟡 Planned | `backend/auth/scim.py` – stub exists. Full SCIM 2.0 endpoint planned for Q4 2026. |
| 1.7 | Periodic access reviews (quarterly user access certification) | 🟡 Planned | Workflow to be built in admin dashboard. Manual process documented in `docs/ops/access-review-runbook.md`. |
| 1.8 | API key rotation policy (max 90-day lifetime) | ✅ Built | `backend/auth/api_keys.py` → keys have `expires_at` column. Cron job `rotate_expired_keys` runs nightly via `backend/cron/key_rotation.py`. |

---

## 2. Audit Trail (CC7)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 2.1 | Structured, immutable audit logs for all security-relevant events | ✅ Built | `backend/audit/logger.py` → `AuditLogger` writes JSON-lines to append-only S3 bucket (`s3://acx-audit-logs/`). Events: login, logout, role_change, job_create, voice_upload, export, admin_action. |
| 2.2 | Job attempt logging (create, retry, fail, complete) | ✅ Built | `backend/services/job_manager.py` → each state transition emits `AuditEvent(event_type="job.state_change", ...)`. Linked to `job_id` and `org_id`. |
| 2.3 | Voice audit events (clone attempt, similarity block, content flag) | ✅ Built | `backend/services/voice_safety.py:VoiceSafetyChecker` → every check returns a result dict that is persisted via `backend/audit/voice_audit.py:log_voice_check()`. |
| 2.4 | Audit log retention ≥ 1 year | ✅ Built | S3 lifecycle policy: IA after 90 d, Glacier after 365 d, delete after 7 years. Configured in `infra/s3/audit_bucket.tf`. |
| 2.5 | Tamper-evident log chain (hash chaining / signed batches) | ✅ Built | `backend/audit/integrity.py` → each log batch includes `prev_hash` (SHA-256 chain). Signed with org-level KMS key. |
| 2.6 | Audit log access restricted to security team | ✅ Built | S3 bucket policy allows only `acx-security-*` IAM roles. Access logged via CloudTrail. |
| 2.7 | Real-time alerting on critical audit events | 🟡 Planned | `backend/audit/alerts.py` – stub. Integration with PagerDuty/Slack planned. |

---

## 3. Availability (A1)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 3.1 | Defined SLOs: 99.9% API uptime, 99.5% TTS job completion | ✅ Built | SLOs documented in `docs/slo/availability.md`. Tracked via Prometheus (`acx_api_requests_total`, `acx_tts_jobs_completed_total`). |
| 3.2 | Health check endpoints for all services | ✅ Built | `/healthz` (liveness) and `/readyz` (readiness) on each FastAPI service. `backend/health/checks.py` → checks DB, Redis, S3, GPU queue. |
| 3.3 | Load balancing and horizontal scaling | ✅ Built | Kubernetes HPA on `acx-api` and `acx-tts-worker` deployments. Config in `infra/k8s/hpa.yaml`. |
| 3.4 | Circuit breaker for external dependencies | ✅ Built | `backend/infra/circuit_breaker.py` → wraps calls to external TTS engines and storage. Thresholds: 5 failures in 60 s → open for 30 s. |
| 3.5 | Automated failover / multi-AZ deployment | ✅ Built | PostgreSQL via RDS Multi-AZ. Redis via ElastiCache Multi-AZ. API pods spread across 3 AZs (`topology.kubernetes.io/zone` anti-affinity). |
| 3.6 | Disaster recovery: RTO ≤ 4 h, RPO ≤ 1 h | ✅ Built | DB snapshots every 30 min. S3 cross-region replication to `us-west-2`. DR runbook: `docs/ops/disaster-recovery.md`. |
| 3.7 | Chaos engineering / regular failover drills | 🟡 Planned | Litmus Chaos experiments in staging. Quarterly DR drill calendar in `docs/ops/dr-drill-calendar.md`. |
| 3.8 | DDoS protection | ✅ Built | CloudFront + AWS Shield Standard. WAF rate-limiting rules in `infra/waf/rate_limit.tf`. |

---

## 4. Processing Integrity (PI1)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 4.1 | Quality control pipeline for all TTS output | ✅ Built | `backend/services/qc_pipeline.py` → stages: `mos_score_check`, `spectral_analysis`, `prosody_validation`, `text_alignment_check`. Jobs failing QC are flagged `needs_review`. |
| 4.2 | End-to-end pipeline traces (OpenTelemetry) | ✅ Built | `backend/infra/tracing.py` → OTLP exporter to Jaeger. Every span includes `org_id`, `job_id`, `model_version`. Trace ID propagated across async workers. |
| 4.3 | Input validation & sanitisation | ✅ Built | Pydantic models for all API inputs (`backend/api/schemas/`). File uploads scanned via ClamAV (`backend/services/file_scan.py`). |
| 4.4 | Idempotency for write operations | ✅ Built | `Idempotency-Key` header supported on all mutation endpoints. Keys stored in Redis with 24 h TTL (`backend/infra/idempotency.py`). |
| 4.5 | Data integrity checks (checksums on uploads/downloads) | ✅ Built | SHA-256 computed on upload, stored in `file_meta.sha256`. Verified on download via `backend/services/integrity.py:verify_checksum()`. |
| 4.6 | Model version pinning & rollback | ✅ Built | `backend/services/model_registry.py` → each job records `model_version`. Rollback via `/api/v1/admin/models/rollback`. Canary deploys via K8s `canary` strategy. |
| 4.7 | Error handling: no silent failures, all errors logged | ✅ Built | Global exception handler in `backend/api/exception_handler.py`. Unhandled errors → 500 + audit log entry + Sentry capture. |

---

## 5. Confidentiality (CC6.7, CC6.8)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 5.1 | Encryption at rest (AES-256) for all stored data | ✅ Built | S3 SSE-KMS (`aws:kms`). RDS encryption enabled. EBS volumes encrypted. Redis in-transit + at-rest encryption. |
| 5.2 | Encryption in transit (TLS 1.2+) for all connections | ✅ Built | TLS termination at ALB (min TLS 1.2). Internal service mesh uses mTLS via Istio (`infra/istio/peer_auth.yaml`). |
| 5.3 | Signed URLs for audio file access (time-limited, org-scoped) | ✅ Built | `backend/services/storage.py:generate_signed_url()` → S3 pre-signed URLs, 15-min expiry, scoped to `org/{org_id}/` prefix. |
| 5.4 | Secret management via vault / KMS (no plaintext secrets in code or config) | ✅ Built | AWS Secrets Manager for DB creds, API keys. Kubernetes External Secrets Operator (`infra/k8s/external_secrets.yaml`). Git-secrets pre-commit hook. |
| 5.5 | Automatic secret redaction in logs | ✅ Built | `backend/audit/redaction.py` → regex + entropy-based redaction applied to all log output. Patterns: API keys, JWTs, SSNs, credit cards. |
| 5.6 | Key rotation for encryption keys (≤ 90 days) | ✅ Built | KMS automatic annual rotation enabled. Application-level data-encryption keys rotated quarterly via `backend/cron/key_rotation.py`. |
| 5.7 | Network segmentation (public vs private subnets) | ✅ Built | VPC with public (ALB only), private (app), and isolated (DB) subnets. Security groups restrict traffic: `infra/vpc/security_groups.tf`. |

---

## 6. Privacy (P1–P8, GDPR)

| # | Requirement | Status | Implementation / Code Reference |
|---|-------------|--------|---------------------------------|
| 6.1 | Data Processing Agreement (DPA) with all sub-processors | 🟡 Planned | DPA templates drafted. Sub-processor list in `docs/legal/sub-processors.md`. Signing workflow in progress. |
| 6.2 | GDPR Right to Erasure (Article 17) | ✅ Built | `backend/services/privacy.py:erase_user_data()` → deletes user PII, anonymises audit logs, removes S3 objects, purges voice embeddings. Completes within 72 h. API: `DELETE /api/v1/users/me`. |
| 6.3 | Data retention sweeper (auto-delete expired data) | ✅ Built | `backend/cron/retention_sweeper.py` → runs nightly. Retention policies: raw audio 30 d, job metadata 1 year, audit logs 7 years. Configurable per org via `retention_policy` table. |
| 6.4 | Data minimisation (collect only what's needed) | ✅ Built | API schemas (`backend/api/schemas/`) use `exclude_unset=True`. Voice reference audio deleted after embedding extraction unless user opts in to storage. |
| 6.5 | Privacy impact assessment (PIA) for new features | 🟡 Planned | PIA template in `docs/compliance/PIA_TEMPLATE.md`. Enforcement via design review checklist. |
| 6.6 | Cookie consent & tracking opt-out (web frontend) | ✅ Built | `frontend/src/components/CookieBanner.vue` → GDPR-compliant consent. Analytics gated on consent state. |
| 6.7 | Data Subject Access Request (DSAR) workflow | ✅ Built | `backend/services/privacy.py:export_user_data()` → generates ZIP of all user data within 30 days. API: `GET /api/v1/users/me/export`. |
| 6.8 | Cross-border data transfer safeguards (SCCs / adequacy) | 🟡 Planned | Data residency config per org (`backend/models/org.py:data_residency_region`). SCCs drafted for EU→US transfers. |
| 6.9 | Breach notification ≤ 72 h (GDPR Article 33) | 🟡 Planned | Incident response runbook: `docs/ops/incident-response.md`. Automated notification pipeline in progress. |

---

## Appendix: Evidence Collection Map

| SOC 2 Criteria | Evidence Source | Location |
|----------------|----------------|----------|
| CC6.1 – Logical access | RBAC matrix, JWT config | `backend/auth/rbac.py`, `backend/auth/models.py` |
| CC6.2 – Authentication | MFA implementation, session mgmt | `backend/auth/mfa.py`, `backend/auth/session.py` |
| CC6.3 – Authorisation | Org-scoped queries, RLS | `backend/db/org_scoping.py`, `alembic/migrations/002_rls_policies.sql` |
| CC7.1 – Monitoring | Audit logs, OTel traces | `backend/audit/logger.py`, `backend/infra/tracing.py` |
| CC7.2 – Anomaly detection | Alert stubs, Sentry | `backend/audit/alerts.py` |
| A1.1 – Capacity | HPA configs, SLO docs | `infra/k8s/hpa.yaml`, `docs/slo/availability.md` |
| PI1.1 – Processing | QC pipeline, model registry | `backend/services/qc_pipeline.py`, `backend/services/model_registry.py` |
| C1.1 – Confidentiality | Encryption configs, signed URLs | `infra/vpc/`, `backend/services/storage.py` |
| P1–P8 – Privacy | Privacy service, retention sweeper | `backend/services/privacy.py`, `backend/cron/retention_sweeper.py` |

---

## Next Steps

1. **Close gaps** on all 🟡 Planned items before engaging auditor.
2. **Collect evidence** — screenshot configs, export IAM policies, collect log samples.
3. **Internal dry-run audit** scheduled for Q4 2026.
4. **Engage auditor** — shortlist: Deloitte, KPMG, Vanta-assisted.
5. **Remediate findings** and book Type I observation window.
