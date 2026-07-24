# Vercel Deployment — ACX City Dashboard

The **admin dashboard** (`dashboard/`) is a Next.js 14 app. It's deployed
separately from the Railway services, on [Vercel](https://vercel.com). It talks
to the Railway-hosted backend API over the public internet, so wiring is just
two things: point it at the backend, and allow its origin in the backend's CORS
list.

---

## Prerequisites

- A [Vercel account](https://vercel.com)
- The backend already deployed on Railway (see [RAILWAY_SETUP.md](./RAILWAY_SETUP.md))
  and reachable at its public URL, e.g. `https://your-backend.up.railway.app`

---

## Step 1 — Import the project

1. Go to [vercel.com/new](https://vercel.com/new)
2. **Import** the `redinc23/acx-city` repository
3. Under **Root Directory**, click **Edit** and select **`dashboard`**
   (this is required — the repo root is not the Next.js app)
4. Framework preset auto-detects as **Next.js**. Leave build/install commands
   at their defaults (they're also pinned in `dashboard/vercel.json`).

---

## Step 2 — Set the environment variable

In the import screen (or later under **Settings → Environment Variables**) add:

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://your-backend.up.railway.app` | The backend's **public** Railway URL. No trailing slash. Embedded in the client bundle at build time. |

> ⚠️ Use the **public** backend URL, not the `*.railway.internal` private
> domain — the dashboard runs in the user's browser, which can't reach the
> private network.

Apply it to **Production**, **Preview**, and **Development** environments.

---

## Step 3 — Allow the dashboard origin in backend CORS

The backend only accepts cross-origin API calls from allow-listed origins. Add
your Vercel domain(s) to `CORS_ALLOW_ORIGINS` on the **backend** Railway service
(comma-separated, no spaces):

```
CORS_ALLOW_ORIGINS=https://your-frontend.up.railway.app,https://your-dashboard.vercel.app
```

Redeploy the backend after changing this. If you use Vercel preview deployments
and want them to hit the live backend, add the preview URL too (or a custom
domain you control).

---

## Step 4 — Deploy

Click **Deploy**. Vercel builds and serves the dashboard. Every push to `main`
triggers a production deploy; pull requests get preview deployments
automatically.

---

## Step 5 — Verify

1. Open your Vercel URL — you should land on `/login`.
2. Sign in with a backend account. On success you're redirected to `/dashboard`.
3. The overview, jobs, and health pages should load live data from the backend.

If API calls fail with a CORS error in the browser console, re-check Step 3.
If they fail with a network error, re-check `NEXT_PUBLIC_API_URL` in Step 2.

---

## Notes

- **Client-only app.** The dashboard reads/writes the backend directly from the
  browser and stores its auth token in `localStorage`. There are no Next.js API
  routes or server components fetching secrets, so no server-side env vars are
  needed beyond `NEXT_PUBLIC_API_URL`.
- **Auth mode.** The login page uses the backend's `/api/auth/login`. With
  `AUTH_MODE=supabase` on the backend, wire the dashboard to your Supabase
  sign-in flow instead (follow-up work).
