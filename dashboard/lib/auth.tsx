'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api, setToken, getToken, AuthResponse } from '@/lib/api'

interface AuthCtx {
  auth: AuthResponse | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const check = getToken()
      ? api.me().then(setAuth).catch(() => setToken(null))
      : Promise.resolve()
    check.finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const data = await api.login(email, password)
    setAuth(data)
  }

  const logout = () => {
    setToken(null)
    setAuth(null)
  }

  return <Ctx.Provider value={{ auth, loading, login, logout }}>{children}</Ctx.Provider>
}

export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}
