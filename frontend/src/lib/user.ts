import { createContext, useContext } from 'react'

export interface UserInfo {
  user_id: number
  username: string
  is_admin: boolean
  can_edit: boolean
}

// Current logged-in user, provided at the app root. Pages read it to decide
// whether to show mutation controls (Edit / New / Save). Note this is only a
// UX affordance — the server independently rejects writes from read-only
// accounts, so hiding a button is never the actual security boundary.
export const UserContext = createContext<UserInfo | null>(null)

export const useUser = (): UserInfo | null => useContext(UserContext)

/** True when the current account is allowed to modify data. */
export const useCanEdit = (): boolean => useContext(UserContext)?.can_edit ?? false