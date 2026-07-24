'use client'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function Home() {
  const { auth, loading } = useAuth()
  const router = useRouter()
  useEffect(() => {
    if (loading) return
    router.replace(auth ? '/dashboard' : '/login')
  }, [auth, loading, router])
  return null
}
