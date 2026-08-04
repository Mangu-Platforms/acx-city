#!/usr/bin/env python3
"""
ACX City Vercel + Domain Setup Automation

This script walks you through deploying the dashboard to Vercel and configuring
a custom domain. It validates prerequisites and generates configuration snippets.

Usage:
  python vercel_setup.py
"""
import sys
import json
from typing import Optional


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def print_step(num: int, title: str):
    """Print a step header."""
    print(f"\n[STEP {num}] {title}")
    print("-" * 80)


def prompt_yes_no(question: str) -> bool:
    """Ask a yes/no question."""
    while True:
        answer = input(f"\n{question} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")


def prompt_url(label: str, default: Optional[str] = None) -> str:
    """Prompt for a URL."""
    if default:
        prompt_text = f"\n{label}\n[default: {default}]: "
    else:
        prompt_text = f"\n{label}: "
    
    value = input(prompt_text).strip()
    if not value and default:
        return default
    if not value:
        print("This field is required.")
        return prompt_url(label, default)
    return value


def main():
    print_header("ACX City — Vercel + Custom Domain Setup")
    
    print("""
This script will guide you through:
  1. Prerequisites check
  2. Vercel deployment configuration
  3. Custom domain setup
  4. Backend CORS configuration
  5. Verification steps
    """)
    
    if not prompt_yes_no("Ready to continue?"):
        print("Exiting.")
        return
    
    # ========================================================================
    # STEP 1: Prerequisites
    # ========================================================================
    print_step(1, "Prerequisites Check")
    
    print("""
Before deploying, you'll need:
  ✓ A Vercel account (free tier: vercel.com)
  ✓ GitHub push access to Mangu-Platforms/acx-city
  ✓ Backend running on Railway with a public URL
  ✓ (Optional) A custom domain name + DNS provider access
    """)
    
    backend_url = prompt_url(
        "Enter your Railway backend URL",
        "https://acx-city-backend.up.railway.app"
    )
    
    has_custom_domain = prompt_yes_no("Do you have a custom domain?")
    custom_domain = None
    if has_custom_domain:
        custom_domain = prompt_url("Enter your custom domain (e.g., admin.yourdomain.com)")
    
    # ========================================================================
    # STEP 2: Vercel Configuration
    # ========================================================================
    print_step(2, "Vercel Deployment Configuration")
    
    vercel_config = {
        "backend_url": backend_url,
        "custom_domain": custom_domain,
        "vercel_url": None,  # Will be assigned by Vercel
    }
    
    print(f"""
VERCEL DEPLOYMENT CHECKLIST:

1. Go to https://vercel.com/new
2. Click "Import Git Repository"
3. Connect and select: Mangu-Platforms/acx-city
4. Under "Project Settings":
   ✓ Framework Preset: Next.js (auto-detected)
   ✓ Root Directory: dashboard (click Edit and select it)
   ✓ Build Command: npm run build
   ✓ Install Command: npm install

5. Click "Environment Variables" and add:
   Name:  NEXT_PUBLIC_API_URL
   Value: {backend_url}
   ⚠️  Important: Use the PUBLIC Railway URL, not .railway.internal

6. Apply to: Production, Preview, Development

7. Click "Deploy" and wait 2-3 minutes

After deployment, Vercel will assign you a URL:
   https://acx-city-XXXXX.vercel.app
    """)
    
    vercel_default_url = prompt_url(
        "Enter the Vercel URL assigned to your dashboard",
        "https://acx-city-XXXXX.vercel.app"
    )
    vercel_config["vercel_url"] = vercel_default_url
    
    # ========================================================================
    # STEP 3: Custom Domain (Optional)
    # ========================================================================
    if has_custom_domain:
        print_step(3, "Custom Domain Configuration")
        
        dns_provider = prompt_url(
            "Enter your DNS provider (Route53, Namecheap, Cloudflare, GoDaddy, etc.)"
        )
        
        use_nameservers = prompt_yes_no(
            "Use Vercel's nameservers? (simpler, recommended)"
        )
        
        if use_nameservers:
            print(f"""
CUSTOM DOMAIN SETUP (Nameservers):

1. In Vercel Dashboard → Settings → Domains
2. Click "Add" and enter: {custom_domain}
3. Vercel will show nameservers, e.g.:
   ns1.vercel-dns.com
   ns2.vercel-dns.com
   ns3.vercel-dns.com
   ns4.vercel-dns.com

4. Go to {dns_provider} and change your domain's nameservers to Vercel's
5. Wait 15-30 minutes for propagation
6. Status will change to "Verified" in Vercel

TIP: Check propagation:
  nslookup {custom_domain}
  # Should resolve to Vercel's IP
            """)
        else:
            print(f"""
CUSTOM DOMAIN SETUP (CNAME):

1. In Vercel Dashboard → Settings → Domains
2. Click "Add" and enter: {custom_domain}
3. Vercel will show a CNAME value, e.g.: cname.vercel-dns.com

4. Go to {dns_provider} and create:
   Name:  admin  (or subdomain of your choice)
   Type:  CNAME
   Value: cname.vercel-dns.com

5. Wait 15-30 minutes for propagation
6. Status will change to "Verified" in Vercel
            """)
    
    # ========================================================================
    # STEP 4: Backend CORS Configuration
    # ========================================================================
    print_step(4, "Backend CORS Configuration")
    
    cors_origins = [vercel_default_url]
    if custom_domain:
        cors_origins.append(f"https://{custom_domain}")
    
    cors_value = ",".join(cors_origins)
    
    print(f"""
UPDATE BACKEND CORS ALLOWLIST:

1. Go to your Railway dashboard
2. Select the "backend" service
3. Click "Variables"
4. Find or create: CORS_ALLOW_ORIGINS
5. Set the value to (comma-separated, no spaces):

   {cors_value}

6. Click "Save"
7. Railway will auto-redeploy the backend
8. Wait 2-3 minutes for the deployment to complete

This allows the dashboard to make API calls to the backend.
    """)
    
    cors_added = prompt_yes_no("Have you updated CORS_ALLOW_ORIGINS and deployed the backend?")
    
    if not cors_added:
        print("\n⚠️  You'll need to do this manually before the dashboard can call the backend.")
    
    # ========================================================================
    # STEP 5: Verification
    # ========================================================================
    print_step(5, "Verification & Testing")
    
    dashboard_url = custom_domain or vercel_default_url
    if not dashboard_url.startswith("https://"):
        dashboard_url = f"https://{dashboard_url}"
    
    print(f"""
VERIFY YOUR DEPLOYMENT:

1. Visit: {dashboard_url}
2. You should see the Login page
3. Sign in with a backend account
4. Open DevTools (F12) → Console tab
5. Check for CORS errors (red X icons)
6. Navigate to:
   - /dashboard (overview)
   - /jobs (job list)
   - /health (system health)

All pages should load data from your backend.

TROUBLESHOOTING:

If you see CORS errors:
  → Re-check Step 4, wait 2-3 minutes for backend redeploy

If you see network errors:
  → Verify NEXT_PUBLIC_API_URL matches your backend URL
  → Check that backend is online and accessible

If domain doesn't resolve:
  → Wait 30 minutes and try again
  → Run: nslookup {dashboard_url.replace('https://', '')}
    """)
    
    # ========================================================================
    # Summary
    # ========================================================================
    print_header("Configuration Summary")
    
    summary = {
        "Backend URL": backend_url,
        "Dashboard (Vercel)": vercel_default_url,
        "Custom Domain": custom_domain or "(none)",
        "CORS Allowlist": cors_value,
    }
    
    for key, value in summary.items():
        print(f"  {key:.<30} {value}")
    
    print("""
    
✅ Next Steps:
  1. Deploy to Vercel (Step 2)
  2. Add custom domain to Vercel (Step 3, if applicable)
  3. Update backend CORS (Step 4)
  4. Test the dashboard (Step 5)
  5. Deploy the frontend (Vite SPA) separately
  
📚 Reference:
  - Full guide: VERCEL_DOMAIN_SETUP.md
  - Original Vercel setup: VERCEL_SETUP.md
  - Railway backend: RAILWAY_SETUP.md
    """)
    
    print_header("Done!")
    print("Your deployment configuration is ready. Follow the steps above to complete the setup.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
