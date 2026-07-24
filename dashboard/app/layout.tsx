'use client'
import './globals.css'
import type { Metadata } from 'next'
import { AuthProvider } from '@/lib/auth'

// Note: metadata export is intentionally kept — Next.js ignores it in
// 'use client' layouts but it does not error.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  )
}
