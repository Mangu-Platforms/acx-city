---
name: mangu-web-platform
description: Apply the MANGU Web Foundation standards when planning, scaffolding, reviewing, or modifying a web application that uses the MANGU stack. Use when a user mentions the MANGU foundation, MANGU-standard web stack, shared Redinc23 web conventions, or asks to make a project consistent with the MANGU web platform.
---

# MANGU Web Platform

Use this skill as a shared engineering baseline, not as a demand to copy the
MANGU Publishers product. Preserve the target project's stated requirements and
existing patterns when they are more specific.

## Apply the foundation

Default to:

- Next.js App Router, React, strict TypeScript, Tailwind CSS, accessible UI,
  and Zod for validation.
- Clear server/client boundaries. Keep credentials and privileged service calls
  server-only; only expose deliberately allowlisted `NEXT_PUBLIC_*` values.
- App Router route groups, `app/api/` for HTTP endpoints, `components/ui/` for
  reusable primitives, and `lib/` for domain-independent utilities/services.
- ESLint, Prettier, type checking, unit tests, and Playwright coverage
  proportional to the risk of the change.
- Environment examples and validation; never put real secrets in code, docs,
  examples, test fixtures, logs, or agent output.
- A health/readiness endpoint and observability setup where the deployed app
  has external dependencies.

Read [foundation.md](references/foundation.md) before selecting services,
extracting code, or making architecture decisions.

## Choose capabilities explicitly

Do not install services merely because MANGU Publishers happens to use them.
Select each of these only when the project needs it:

- Supabase for PostgreSQL, auth, storage, and RLS.
- Stripe for payments and webhooks.
- Resend for transactional email.
- OpenAI for AI capabilities.
- Sentry for production error monitoring.
- Upstash for rate limiting when public, authenticated, paid, or costly API
  access needs abuse controls.

Select exactly one canonical authentication provider and one canonical data
provider per project. Do not scaffold MANGU's historical dual-provider
migration state into a new application.

## Architecture and change rules

1. Prefer existing project patterns before creating abstractions.
2. Keep product data models, feature routes, and business logic out of the
   foundation unless they are genuinely cross-product.
3. Use a short ADR before changing the project’s deployment platform,
   authentication provider, or primary database.
4. Keep payment webhooks idempotent and test duplicate delivery behavior.
5. Treat schema migrations as ordered, reviewable application changes; never
   copy MANGU's publishing migrations into another product.
6. Use a single canonical production platform per project. Retain fallback
   configurations only with a documented operational reason.

## Verify before completion

Run the project’s equivalents of:

```bash
npm run lint
npm run type-check
npm test
npx playwright test
npm run build
```

If an external service, credential, or production console prevents a check,
state the precise blocker and verify every safe local check instead.

## Scope boundaries

Do not import MANGU Publishers-specific content into a general project:

- publishing, reader, author, audiobook, partner, recommendation, payout, or
  marketplace models and UI;
- Project Phoenix migration/cutover rules or dual-provider flags;
- MANGU launch ledgers, internal domains, historical runbooks, or legacy Cloud
  Run/AWS compatibility artifacts.

For the reusable-vs-product boundary and module choices, read
[foundation.md](references/foundation.md).
