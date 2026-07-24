import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // The backend API URL is injected at build time via NEXT_PUBLIC_API_URL.
  // All API calls are made client-side from the browser, so no server-side
  // proxy is needed — the backend must have CORS set to allow the dashboard origin.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? '',
  },
}

export default nextConfig
