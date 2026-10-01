import { useEffect, useState } from 'react'
import { clearSession, loadSession, onUnauthorized, saveSession, type Session } from './api'
import Chat from './Chat'
import Console from './Console'
import Login from './Login'

export default function App() {
  const [session, setSession] = useState<Session | null>(() => loadSession())

  // Any 401 from the API clears the session and shows Login again.
  useEffect(() => {
    onUnauthorized(() => setSession(null))
    return () => onUnauthorized(null)
  }, [])

  const login = (next: Session) => {
    saveSession(next)
    setSession(next)
  }

  const logout = () => {
    void clearSession()
    setSession(null)
  }

  if (!session) return <Login onLogin={login} />
  if (session.app_role === 'agent') return <Console session={session} onLogout={logout} />
  return <Chat session={session} onLogout={logout} />
}
