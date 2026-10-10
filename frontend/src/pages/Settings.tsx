import { useState } from 'react'
import { api } from '../api'

export default function Settings() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage('')
    setError('')
    try {
      await api.post('/api/auth/change_password', {
        current_password: current,
        new_password: next,
      })
      setMessage('Password changed ✔')
      setCurrent('')
      setNext('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error')
    }
  }

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">⚙️ Settings</h1>
      <form onSubmit={submit} className="space-y-4 rounded-xl bg-white p-4 shadow">
        <h2 className="font-semibold">Change password</h2>
        <label className="block">
          <span className="text-sm font-medium">Current password</span>
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-slate-300 p-3"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">New password (min 6 chars)</span>
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-slate-300 p-3"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </label>
        {message && <p className="text-sm text-green-600">{message}</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          disabled={!current || next.length < 6}
          className="w-full rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50"
        >
          Change password
        </button>
      </form>
    </div>
  )
}
