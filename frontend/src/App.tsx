import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowLeftRight, BarChart3, Boxes, Clock, Database, PartyPopper,
  Plus, Receipt, Settings, Wallet,
} from 'lucide-react'
import {
  HashRouter, Link, Navigate, Route, Routes, useLocation, useNavigate,
} from 'react-router-dom'
import { api } from './api'
import Activity from './pages/Activity'
import Dashboard from './pages/Dashboard'
import EntityForm from './pages/EntityForm'
import EntityList from './pages/EntityList'
import ExpenseDetail from './pages/ExpenseDetail'
import ExpenseForm from './pages/ExpenseForm'
import Expenses from './pages/Expenses'
import Inventory from './pages/Inventory'
import InventoryForm from './pages/InventoryForm'
import MasterHome from './pages/MasterHome'
import Money from './pages/Money'
import OrderDetail from './pages/OrderDetail'
import OrderForm from './pages/OrderForm'
import Orders from './pages/Orders'
import ProductList from './pages/ProductList'
import Reports from './pages/Reports'
import Richie from './pages/Richie'
import SettingsPage from './pages/Settings'
import Stock from './pages/Stock'
import TransferDetail from './pages/TransferDetail'
import TransferForm from './pages/TransferForm'
import Transfers from './pages/Transfers'
import Work from './pages/Work'
import WorkDetail from './pages/WorkDetail'
import WorkForm from './pages/WorkForm'
import { UserContext, type UserInfo } from './lib/user'

export type { UserInfo }

// Navigation is resource-centric (nouns): each tab is a place to *view* a resource.
const TABS = [
  { to: '/dashboard', label: 'Analytics', Icon: BarChart3, match: (p: string) => p.startsWith('/dashboard') },
  { to: '/order', label: 'Orders', Icon: PartyPopper, match: (p: string) => p.startsWith('/order') },
  { to: '/stock', label: 'Stock', Icon: Boxes, match: (p: string) => p.startsWith('/stock') || p.startsWith('/inventory_update') },
  { to: '/money', label: 'Money', Icon: Wallet, match: (p: string) => p.startsWith('/money') || p.startsWith('/expense') || p.startsWith('/transfer') },
  { to: '/work', label: 'Time', Icon: Clock, match: (p: string) => p.startsWith('/work') },
  { to: '/master', label: 'Master', Icon: Database, match: (p: string) => ['/master', '/e/', '/composition', '/activity', '/reports', '/richie', '/settings'].some((s) => p.startsWith(s)) },
]

// Input is event-centric (verbs): record a real-world fact from anywhere.
const QUICK_ADD = [
  { label: 'Order', Icon: PartyPopper, to: '/order/new' },
  { label: 'Expense', Icon: Receipt, to: '/expense/new' },
  { label: 'Stock Update', Icon: Boxes, to: '/inventory_update/new' },
  { label: 'Work Time', Icon: Clock, to: '/work/new' },
  { label: 'Money Transfer', Icon: ArrowLeftRight, to: '/transfer/new' },
]

function TopBar({ user }: { user: UserInfo }) {
  return (
    <header className="sticky top-0 z-20 overflow-hidden bg-gradient-to-r from-violet-600 to-sky-500 text-white shadow pt-[env(safe-area-inset-top)]">
      <div className="pointer-events-none absolute -left-6 -top-8 h-24 w-24 rounded-full bg-white/10" />
      <div className="pointer-events-none absolute right-10 -top-10 h-20 w-20 rounded-full bg-white/10" />
      <div className="pointer-events-none absolute right-24 top-2 h-8 w-8 rounded-full bg-white/10" />
      <div className="relative flex items-center justify-between px-4 py-3">
        <Link to="/dashboard" className="text-lg font-bold tracking-wide">🎈 AI.R public demo</Link>
        <div className="flex items-center gap-3">
          <span className="text-sm opacity-80">{user.username}</span>
          <Link to="/settings" aria-label="settings" className="opacity-90 hover:opacity-100">
            <Settings size={20} />
          </Link>
        </div>
      </div>
    </header>
  )
}

function QuickAdd() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const go = (to: string) => { setOpen(false); navigate(to) }

  // Draggable FAB: press-and-drag the + to move it anywhere (position persisted),
  // a plain tap opens the menu. Lets the user clear content it overlaps — e.g.
  // the bottom-right Master cards on small screens.
  const [pos, setPos] = useState<{ right: number; bottom: number }>(() => {
    try { const s = localStorage.getItem('air:fabPos'); if (s) return JSON.parse(s) } catch { /* ignore */ }
    return { right: 16, bottom: 88 }
  })
  useEffect(() => {
    try { localStorage.setItem('air:fabPos', JSON.stringify(pos)) } catch { /* ignore */ }
  }, [pos])
  const drag = useRef<{ x: number; y: number; right: number; bottom: number; moved: boolean } | null>(null)
  const onPointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, right: pos.right, bottom: pos.bottom, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) d.moved = true
    const clamp = (v: number, hi: number) => Math.min(Math.max(v, 8), Math.max(8, hi))
    setPos({
      right: clamp(d.right - dx, window.innerWidth - 64),
      bottom: clamp(d.bottom - dy, window.innerHeight - 64),
    })
  }
  const onPointerUp = () => {
    const d = drag.current
    drag.current = null
    if (d && !d.moved) setOpen((o) => !o) // tap (not drag) toggles the menu
  }

  return (
    <>
      {open && <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />}
      <div className="fixed z-40 flex flex-col items-end gap-2" style={{ right: pos.right, bottom: pos.bottom }}>
        {open && QUICK_ADD.map((a) => (
          <button key={a.to} onClick={() => go(a.to)}
            className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-lg">
            <a.Icon size={18} className="text-violet-600" /> {a.label}
          </button>
        ))}
        <button onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
          aria-label="quick add"
          className="flex h-14 w-14 touch-none items-center justify-center rounded-full bg-violet-600 text-white shadow-lg">
          <Plus size={26} className={`transition-transform ${open ? 'rotate-45' : ''}`} />
        </button>
      </div>
    </>
  )
}

function BottomNav() {
  const { pathname } = useLocation()
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_6px_rgba(0,0,0,0.06)]">
      {TABS.map(({ to, label, Icon, match }) => {
        const active = match(pathname)
        return (
          <Link key={to} to={to}
            className={`flex flex-1 flex-col items-center gap-0.5 py-1.5 text-[11px] font-medium ${active ? 'text-violet-600' : 'text-slate-400'}`}>
            <span className={`flex h-8 w-12 items-center justify-center rounded-full transition-colors ${active ? 'bg-violet-100' : ''}`}>
              <Icon size={21} strokeWidth={active ? 2.4 : 1.8} />
            </span>
            {label}
          </Link>
        )
      })}
    </nav>
  )
}

export default function App() {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [checked, setChecked] = useState(false)

  // Public demo: there is no login screen. Reuse an existing session if present,
  // otherwise sign in silently as the shared demo account.
  const signInDemo = useCallback(async (): Promise<UserInfo | null> => {
    try {
      return await api.post<UserInfo>('/api/auth/login', { username: 'al', password: 'demo1234' })
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    (async () => {
      try {
        setUser(await api.get<UserInfo>('/api/auth/me'))
      } catch {
        setUser(await signInDemo())
      } finally {
        setChecked(true)
      }
    })()
  }, [signInDemo])

  // If the session expires mid-use (401 from `api`), silently sign back in so
  // the demo never interrupts the visitor with a login screen.
  useEffect(() => {
    const onUnauthorized = async () => setUser(await signInDemo())
    window.addEventListener('air:unauthorized', onUnauthorized)
    return () => window.removeEventListener('air:unauthorized', onUnauthorized)
  }, [signInDemo])

  if (!checked) return <div className="p-8 text-center text-slate-500">Loading…</div>
  if (!user) return <div className="p-8 text-center text-slate-500">Demo unavailable — is the backend running?</div>

  return (
    <UserContext.Provider value={user}>
    <HashRouter>
      <div className="min-h-screen bg-slate-100">
        <TopBar user={user} />
        <main className="mx-auto max-w-3xl pb-24">
          <Routes>
            <Route path="/" element={<Navigate to="/order" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/master" element={<MasterHome />} />
            <Route path="/e/product" element={<ProductList />} />
            <Route path="/e/:entity" element={<EntityList />} />
            <Route path="/e/:entity/new" element={<EntityForm />} />
            <Route path="/e/:entity/:id" element={<EntityForm />} />
            <Route path="/order" element={<Orders />} />
            <Route path="/order/new" element={<OrderForm />} />
            <Route path="/order/:id" element={<OrderDetail />} />
            <Route path="/order/:id/edit" element={<OrderForm />} />
            <Route path="/money" element={<Money />} />
            <Route path="/expense" element={<Expenses />} />
            <Route path="/expense/new" element={<ExpenseForm />} />
            <Route path="/expense/:id" element={<ExpenseDetail />} />
            <Route path="/expense/:id/edit" element={<ExpenseForm />} />
            <Route path="/transfer" element={<Transfers />} />
            <Route path="/transfer/new" element={<TransferForm />} />
            <Route path="/transfer/:id" element={<TransferDetail />} />
            <Route path="/transfer/:id/edit" element={<TransferForm />} />
            <Route path="/work" element={<Work />} />
            <Route path="/work/new" element={<WorkForm />} />
            <Route path="/work/:id" element={<WorkDetail />} />
            <Route path="/work/:id/edit" element={<WorkForm />} />
            <Route path="/inventory_update" element={<Inventory />} />
            <Route path="/inventory_update/new" element={<InventoryForm />} />
            <Route path="/inventory_update/:id" element={<InventoryForm />} />
            <Route path="/inventory_update/:id/edit" element={<InventoryForm />} />
            <Route path="/stock" element={<Stock />} />
            <Route path="/activity" element={<Activity />} />
            {/* Import is an input-only tool: never reachable by read-only accounts,
                even via a direct URL. */}
            <Route path="/richie" element={user.can_edit ? <Richie /> : <Navigate to="/master" replace />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/order" replace />} />
          </Routes>
        </main>
        {user.can_edit && <QuickAdd />}
        <BottomNav />
      </div>
    </HashRouter>
    </UserContext.Provider>
  )
}
