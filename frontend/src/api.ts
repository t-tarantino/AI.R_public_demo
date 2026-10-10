// Minimal fetch wrapper for the AI.R backend API.
// Session is a httpOnly cookie: always send credentials.
import { invalidateOptions } from './lib/optionsCache'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const resp = await fetch(url, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    // A 401 on anything other than the auth endpoints means the session expired
    // (or the cookie is gone) mid-use: tell the app to drop back to the login
    // screen instead of leaving the user stuck on error messages. Auth routes
    // (login/me) handle their own 401 locally, so they are excluded.
    if (resp.status === 401 && !url.startsWith('/api/auth/')) {
      window.dispatchEvent(new Event('air:unauthorized'))
    }
    let message = `Errore ${resp.status}`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) {
        message = data.detail
          .map((d: { loc?: unknown[]; msg?: string }) =>
            `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? ''}`)
          .join('; ')
      }
    } catch { /* keep default message */ }
    throw new ApiError(resp.status, message)
  }
  // Any write may change reference lists (parties, products, colours…), so drop
  // the cached dropdown data; the next read fetches it fresh.
  if (method !== 'GET') invalidateOptions()
  return resp.json() as Promise<T>
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  delete: <T>(url: string) => request<T>('DELETE', url),
}