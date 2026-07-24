import React, { useEffect, useState } from 'react'
import { Book, LogOut } from 'lucide-react'
import { audiobookAPI, getToken, AuthResponse } from '../services/api'

interface AuthGateProps {
  children: (auth: AuthResponse, logout: () => void) => React.ReactNode
}

/**
 * Gates the app behind login/signup. A job id no longer authorizes access on the
 * backend, so the UI must present a real session before calling protected APIs.
 */
export const AuthGate: React.FC<AuthGateProps> = ({ children }) => {
  const [auth, setAuth] = useState<AuthResponse | null>(null)
  const [checking, setChecking] = useState(true)
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      setChecking(false)
      return
    }
    audiobookAPI.me()
      .then(setAuth)
      .catch(() => audiobookAPI.logout())
      .finally(() => setChecking(false))
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = mode === 'login'
        ? await audiobookAPI.login(email, password)
        : await audiobookAPI.signup(email, password, displayName || undefined)
      setAuth(res)
    } catch (err: any) {
      setError(err?.response?.data?.error || 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  const logout = () => {
    audiobookAPI.logout()
    setAuth(null)
  }

  if (checking) {
    return <div className="min-h-screen flex items-center justify-center text-gray-500">Loading…</div>
  }

  if (auth) {
    return <>{children(auth, logout)}</>
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white rounded-lg shadow-sm border p-8">
        <div className="flex items-center space-x-3 mb-6">
          <Book className="h-8 w-8 text-blue-600" />
          <h1 className="text-xl font-bold text-gray-900">Audiobook Producer</h1>
        </div>
        <h2 className="text-lg font-semibold text-gray-800 mb-4">
          {mode === 'login' ? 'Sign in' : 'Create your account'}
        </h2>
        <form onSubmit={submit} className="space-y-4">
          {mode === 'signup' && (
            <input value={displayName} onChange={e => setDisplayName(e.target.value)}
              placeholder="Your name (optional)"
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" />
          )}
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" />
          <input type="password" required value={password} onChange={e => setPassword(e.target.value)}
            placeholder="Password (min 8 characters)"
            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" disabled={busy}
            className="w-full py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:bg-gray-400">
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <button
          onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setError(null) }}
          className="mt-4 text-sm text-blue-600 hover:underline">
          {mode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  )
}

export const LogoutButton: React.FC<{ onLogout: () => void; email?: string }> = ({ onLogout, email }) => (
  <button onClick={onLogout}
    className="flex items-center space-x-2 text-sm text-gray-500 hover:text-gray-800">
    <LogOut className="h-4 w-4" />
    <span>{email ? `Sign out (${email})` : 'Sign out'}</span>
  </button>
)
