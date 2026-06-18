import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getMe, type UserProfile } from '../services/api'

interface AuthContextValue {
  token: string | null
  user: UserProfile | null
  loading: boolean
  loginWithResponse: (token: string, username: string, user: UserProfile) => void
  logout: () => void
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredUser() {
  const raw = localStorage.getItem('auth_user')
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserProfile
  } catch {
    localStorage.removeItem('auth_user')
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [user, setUser] = useState<UserProfile | null>(() => readStoredUser())
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem('token')))

  const clearAuth = useCallback(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('auth_user')
    setToken(null)
    setUser(null)
  }, [])

  const refreshMe = useCallback(async () => {
    if (!localStorage.getItem('token')) {
      setLoading(false)
      clearAuth()
      return
    }
    setLoading(true)
    try {
      const currentUser = await getMe()
      localStorage.setItem('auth_user', JSON.stringify(currentUser))
      localStorage.setItem('username', currentUser.username)
      setUser(currentUser)
      setToken(localStorage.getItem('token'))
    } catch {
      clearAuth()
    } finally {
      setLoading(false)
    }
  }, [clearAuth])

  useEffect(() => {
    refreshMe()
  }, [refreshMe])

  const loginWithResponse = useCallback((nextToken: string, username: string, nextUser: UserProfile) => {
    localStorage.setItem('token', nextToken)
    localStorage.setItem('username', username)
    localStorage.setItem('auth_user', JSON.stringify(nextUser))
    setToken(nextToken)
    setUser(nextUser)
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    token,
    user,
    loading,
    loginWithResponse,
    logout: clearAuth,
    refreshMe,
  }), [token, user, loading, loginWithResponse, clearAuth, refreshMe])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
