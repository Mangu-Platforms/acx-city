import './globals.css'
import type { Metadata } from 'next'
import { AuthProvider } from '@/lib/auth'

export const metadata: Metadata = {
  title: 'ACX City — Ops Dashboard',
  description: 'Internal operations dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  )
}
