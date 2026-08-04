# Vercel Deployment + Custom Domain Setup — ACX City Dashboard

This guide walks you through deploying the dashboard to Vercel and connecting your custom domain.

---

## Quick Start (5 minutes)

1. **Deploy to Vercel** (Step 1 below)
2. **Add custom domain** (Step 3 below)
3. **Update backend CORS** (Step 4 below)
4. **Verify** (Step 5 below)

---

## Step 1: Deploy Dashboard to Vercel

### Prerequisites
- A [Vercel account](https://vercel.com) (free tier is sufficient)
- Backend already deployed on Railway with a public URL (e.g., `https://backend-xyz.up.railway.app`)
- Admin access to your GitHub repo

### Deploy
1. Visit **[vercel.com/new](https://vercel.com/new)**
2. **Import Git Repository** → Connect `Mangu-Platforms/acx-city`
3. Under **Project Settings**:
   - **Framework Preset:** Next.js (auto-detected)
   - **Root Directory:** Click **Edit** → Select `dashboard`
   - **Build Command:** `npm run build` (pinned in `dashboard/vercel.json`)
   - **Install Command:** `npm install`

4. Click **Environment Variables** and add:
   ```
   Name:  NEXT_PUBLIC_API_URL
   Value: https://your-backend-url.up.railway.app
   ```
   - **Important:** Use the **public** Railway URL, not the `.railway.internal` private domain
   - No trailing slash
   - Apply to all environments (Production, Preview, Development)

5. Click **Deploy**
6. Wait 2-3 minutes for build to complete
7. Vercel assigns you a URL like `https://acx-city-xxx.vercel.app` ✅

---

## Step 2: Verify Dashboard Works

1. Visit your new Vercel URL
2. You should see the **Login** page
3. Open browser DevTools → **Network** tab
4. Try logging in — API calls should reach your backend without CORS errors
5. If CORS errors appear, you'll need to update backend CORS in Step 4

---

## Step 3: Add Custom Domain

### Option A: Use Vercel's Free Domain (Skip This If You Have Your Own)
Vercel gives you a free subdomain. You're already using it! Skip to Step 4.

### Option B: Connect Your Own Domain

#### 3a. Add domain to Vercel
1. Go to your **Vercel Dashboard**
2. Select your **acx-city** project
3. Click **Settings** → **Domains**
4. Click **Add** and enter your domain:
   ```
   admin.yourdomain.com
   ```
5. Vercel shows DNS configuration (keep this window open)

#### 3b. Point DNS to Vercel
You'll see one of two options:

**Option 1: Vercel Nameservers** (Recommended for simplicity)
- Copy the nameservers Vercel provides
- Go to your domain registrar (Route53, Namecheap, Cloudflare, GoDaddy, etc.)
- Change the nameservers to Vercel's
- Wait 15-30 minutes for propagation
- Status changes to **Verified** in Vercel

**Option 2: CNAME Records** (If you want to keep your current nameservers)
- Create a CNAME record in your DNS provider:
  ```
  Name:  admin
  Type:  CNAME
  Value: cname.vercel-dns.com
  ```
- Wait 15-30 minutes
- Status changes to **Verified** in Vercel

#### 3c. Verify domain is live
```bash
# Wait 15-30 minutes, then:
curl -I https://admin.yourdomain.com
# Should return 200 and redirect to /login
```

---

## Step 4: Update Backend CORS Configuration

The backend only accepts API calls from allowed origins. Add your Vercel domain to the CORS allowlist.

### On Railway (Backend)
1. Go to your **Railway project**
2. Click the **backend** service
3. Click **Variables**
4. Find (or create) `CORS_ALLOW_ORIGINS`
5. Add your Vercel domain(s):
   ```
   https://acx-city-xxx.vercel.app,https://admin.yourdomain.com
   ```
   - Comma-separated, **no spaces**
   - Include the main Vercel URL and any custom domains
   - If you use Vercel Preview Deployments, add them too (optional, for testing)

6. Click **Save**
7. **Important:** Railway will auto-redeploy the backend with the new config

Wait 2-3 minutes for the redeploy to complete.

---

## Step 5: Verify End-to-End

1. **Visit your dashboard:**
   ```
   https://admin.yourdomain.com
   ```
   (or the Vercel default URL if you skipped custom domain)

2. **Sign in** with a backend account
3. **Check the browser console** (F12 → Console)
   - No CORS errors
   - API calls succeed

4. **Navigate to:**
   - `/dashboard` — should show the admin overview
   - `/jobs` — should list synthesis jobs from the backend
   - `/health` — should show system health from the backend

If API calls fail with `"error": "CORS policy"`, re-check Step 4 and verify the backend was redeployed.

---

## Step 6: Enable Auto-Deployments (Optional)

Every push to `main` triggers a Vercel production deploy automatically. To add a custom domain for preview deployments:

1. In Vercel → **Settings** → **Domains**
2. Add `preview-*.yourdomain.com` as a wildcard domain (premium feature) or
3. Just test with the Vercel URL: `https://acx-city-pr-123-xyz.vercel.app`

---

## Troubleshooting

### CORS error in browser console
- **Cause:** Dashboard origin not in backend's `CORS_ALLOW_ORIGINS`
- **Fix:** Follow Step 4, wait 2-3 minutes for backend to redeploy

### "Cannot reach backend" / Network error
- **Cause:** `NEXT_PUBLIC_API_URL` is wrong or backend is down
- **Fix:** Check `NEXT_PUBLIC_API_URL` in Vercel env vars (Step 1), verify backend is online

### Domain not resolving
- **Cause:** DNS propagation not complete or misconfigured
- **Fix:** Wait 30 minutes, then run:
  ```bash
  nslookup admin.yourdomain.com
  # Should resolve to Vercel's IP
  ```

### Build fails on Vercel
- **Cause:** Missing dependencies or TypeScript errors
- **Fix:** Check the Vercel build logs, run `npm install && npm run build` locally in `dashboard/`

---

## Summary

| Component | URL | Notes |
|-----------|-----|-------|
| **Backend** | `https://backend-xyz.up.railway.app` | Railway (set in Step 1) |
| **Dashboard** | `https://admin.yourdomain.com` | Vercel (custom domain) |
| **Frontend** | `https://app.yourdomain.com` | Deploy separately (see README.md) |

**Next steps after dashboard is live:**
- Deploy the frontend (Vite SPA) to Railway, Vercel, or a CDN
- Configure frontend CORS + API proxy
- Set up monitoring, logging, and alerting on Railway + Vercel
- Add users and organizations via the dashboard

---

## Files & References

- **Vercel config:** `dashboard/vercel.json`
- **Environment template:** `dashboard/.env.example`
- **Original setup guide:** `VERCEL_SETUP.md`
