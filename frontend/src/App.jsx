import { lazy, Suspense, useEffect, useState, useRef, useCallback } from 'react'
import { Endpoints, onUnauthorized } from './lib/api'
import { useToast } from './lib/toast.jsx'
import { useTheme } from './lib/theme'
import { ensureNotificationPermission, desktopNotify } from './lib/util'
import LoginScreen from './components/LoginScreen.jsx'
import AdminLoginScreen from './components/AdminLoginScreen.jsx'
import Sidebar from './components/Sidebar.jsx'
import TopStats from './components/TopStats.jsx'
import { signOutIdentity } from './lib/supabase'

const AddAccountModal = lazy(() => import('./components/AddAccountModal.jsx'))
const AdminPage = lazy(() => import('./components/AdminPage.jsx'))
const DashboardTab = lazy(() => import('./tabs/DashboardTab.jsx'))
const ProfileTab = lazy(() => import('./tabs/ProfileTab.jsx'))
const SecurityTab = lazy(() => import('./tabs/SecurityTab.jsx'))
const GroupsTab = lazy(() => import('./tabs/GroupsTab.jsx'))
const MessagingTab = lazy(() => import('./tabs/MessagingTab.jsx'))
const InboxTab = lazy(() => import('./tabs/InboxTab.jsx'))
const ProxyTab = lazy(() => import('./tabs/ProxyTab.jsx'))
const TargetCheckTab = lazy(() => import('./tabs/TargetCheckTab.jsx'))
const PhoneCheckTab = lazy(() => import('./tabs/PhoneCheckTab.jsx'))
const BulkTab = lazy(() => import('./tabs/BulkTab.jsx'))
const SettingsTab = lazy(() => import('./tabs/SettingsTab.jsx'))
const ActivityTab = lazy(() => import('./tabs/ActivityTab.jsx'))
const JobsTab = lazy(() => import('./tabs/JobsTab.jsx'))
const AuditTab = lazy(() => import('./tabs/AuditTab.jsx'))
const SystemTab = lazy(() => import('./tabs/SystemTab.jsx'))

const TABS = [
  { id: 'dashboard', label: 'Tổng quan' },
  { id: 'profile',   label: 'Hồ sơ'   },
  { id: 'security',  label: 'Bảo mật'  },
  { id: 'groups',    label: 'Nhóm'    },
  { id: 'messages',  label: 'Gửi tin nhắn'  },
  { id: 'inbox',     label: 'Tin nhắn đến'  },
  { id: 'proxy',     label: 'Proxy'  },
  { id: 'checker',   label: 'Kiểm tra'   },
  { id: 'phone-check', label: 'Check số' },
  { id: 'bulk',      label: 'Hàng loạt'      },
  { id: 'activity',  label: 'Hoạt động realtime' },
  { id: 'jobs',      label: 'Tác vụ'      },
  { id: 'audit',     label: 'Nhật ký'     },
  { id: 'system',    label: 'Hệ thống'    },
  { id: 'settings',  label: 'Cài đặt'  },
]

export default function App() {
  const toast = useToast()
  const { theme, toggle } = useTheme()
  const adminRoute = window.location.pathname.startsWith('/admin')
  const [authState, setAuthState] = useState('checking') // checking | in | out
  const [currentUser, setCurrentUser] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [gone, setGone] = useState([])  // banned/removed account history
  const [stats, setStats] = useState({ total: 0, connected: 0, banned: 0, with_2fa: 0, unread_security: 0 })
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('dashboard')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const prevUnreadRef = useRef(0)
  const [notificationSound, setNotificationSound] = useState(true)

  // initial auth check
  useEffect(() => {
    Endpoints.me()
      .then((r) => { setCurrentUser(r?.user || null); setAuthState(r?.authed ? 'in' : 'out') })
      .catch(() => { setCurrentUser(null); setAuthState('out') })
  }, [])

  // global 401 handler: kick back to login
  useEffect(() => onUnauthorized(() => {
    setAuthState('out')
    setCurrentUser(null)
    setAccounts([]); setGone([]); setSelectedId(null)
  }), [])

  async function logout() {
    try { await Endpoints.logout() } catch {}
    try { await signOutIdentity(adminRoute ? 'admin' : 'user') } catch {}
    setAuthState('out')
    setCurrentUser(null)
    setAccounts([]); setGone([]); setSelectedId(null)
    prevUnreadRef.current = 0
  }

  const refreshAccounts = useCallback(async () => {
    try {
      const list = await Endpoints.accounts()
      setAccounts(list)
      if (!selectedId && list.length) setSelectedId(list[0].id)
    } catch (e) {
      // Stay silent on polling failures — only show error on first-load
      if (accounts.length === 0 && !e.network && e.status !== 401) {
        toast.error('Tải tài khoản: ' + e.message)
      }
    }
  }, [selectedId, toast, accounts.length])

  const refreshGone = useCallback(async () => {
    try { setGone(await Endpoints.goneAccounts()) } catch (e) { /* silent */ }
  }, [])

  const refreshStats = useCallback(async () => {
    try {
      const s = await Endpoints.stats()
      setStats(s)
      if (s.unread_security > prevUnreadRef.current && prevUnreadRef.current !== 0) {
        desktopNotify('Có tin nhắn bảo mật mới', `Chưa đọc: ${s.unread_security}`, notificationSound)
      }
      prevUnreadRef.current = s.unread_security
    } catch (e) { /* silent */ }
  }, [notificationSound])

  useEffect(() => {
    const onSettings = (e) => {
      if (e?.detail && typeof e.detail.notification_sound === 'boolean') {
        setNotificationSound(e.detail.notification_sound)
      }
    }
    window.addEventListener('mtm-settings-updated', onSettings)
    return () => window.removeEventListener('mtm-settings-updated', onSettings)
  }, [])

  useEffect(() => {
    if (authState !== 'in' || adminRoute) return
    Endpoints.getSettings().then((cfg) => setNotificationSound(cfg.notification_sound !== false)).catch(() => {})
    ensureNotificationPermission()
    refreshAccounts()
    refreshStats()
    refreshGone()
    const id = setInterval(() => { refreshAccounts(); refreshStats(); refreshGone() }, 30000)
    return () => clearInterval(id)
  }, [authState, adminRoute, refreshAccounts, refreshStats, refreshGone])

  if (authState === 'checking') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-100 dark:bg-zinc-950">
        <div className="nb-card-sm p-4 font-bold uppercase tracking-tight">Đang tải…</div>
      </div>
    )
  }
  if (authState === 'out') {
    const Login = adminRoute ? AdminLoginScreen : LoginScreen
    return <Login onAuthed={(user) => {
      setCurrentUser(user || null)
      setAuthState(user ? 'in' : 'out')
    }} />
  }

  if (adminRoute) {
    if (currentUser?.role !== 'admin') {
      return <div className="min-h-screen flex items-center justify-center"><div className="nb-card p-6"><b>403 — Phiên hiện tại không có quyền ADMIN</b><br/><button className="nb-btn mt-3" onClick={logout}>Đăng xuất ADMIN</button></div></div>
    }
    return <Suspense fallback={<LazyFallback />}><AdminPage currentUser={currentUser} onLogout={logout} /></Suspense>
  }

  const selected = accounts.find((a) => a.id === selectedId) || null

  return (
    <div className="h-screen w-screen flex flex-col">
      <header className="border-b-2 border-black dark:border-white bg-brand-pri text-black flex items-center px-4 py-2 gap-3">
        <button onClick={() => setSidebarOpen((s) => !s)} className="nb-btn !bg-white !text-black !py-1 !px-2">
          ☰
        </button>
        <h1 className="font-extrabold text-xl uppercase tracking-tighter">Quản Lý Telegram Đa Tài Khoản</h1>
        <div className="flex-1" />
        <span className="text-xs font-bold hidden md:inline">{currentUser?.username}</span>
        <TopStats stats={stats} onBellClick={() => setTab('security')} />
        <button onClick={toggle} className="nb-btn !bg-white !text-black !py-1 !px-2" title="Đổi giao diện">
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        <button onClick={logout} className="nb-btn !bg-white !text-black !py-1 !px-2" title="Đăng xuất">
          ⏻
        </button>
      </header>

      <div className="flex-1 flex min-h-0">
        {sidebarOpen && (
          <Sidebar
            accounts={accounts}
            gone={gone}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onAdd={() => setAddOpen(true)}
            onDeleted={() => { refreshAccounts(); refreshGone() }}
            onGoneChange={refreshGone}
          />
        )}

        <main className="flex-1 min-w-0 flex flex-col">
          <nav className="flex gap-1 px-4 pt-3 flex-wrap border-b-2 border-black dark:border-white bg-zinc-100 dark:bg-zinc-900">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`nb-tab ${tab === t.id ? 'nb-tab-active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="flex-1 min-h-0 overflow-auto p-4">
            <Suspense fallback={<LazyFallback />}>
            {tab === 'dashboard' && <DashboardTab stats={stats} accounts={accounts} onSelect={(id) => { setSelectedId(id); setTab('profile') }} onChange={() => { refreshStats(); refreshAccounts() }} />}
            {tab === 'profile'   && <ProfileTab account={selected} onRefresh={refreshAccounts} />}
            {tab === 'security'  && <SecurityTab accounts={accounts} onChange={refreshStats} />}
            {tab === 'groups'    && <GroupsTab accounts={accounts} selected={selected} />}
            {tab === 'messages'  && <MessagingTab accounts={accounts} selected={selected} />}
            {tab === 'inbox'     && <InboxTab accounts={accounts} selected={selected} />}
            {tab === 'proxy'     && <ProxyTab />}
            {tab === 'checker'   && <TargetCheckTab />}
            {tab === 'phone-check' && <PhoneCheckTab accounts={accounts} />}
            {tab === 'bulk'      && <BulkTab accounts={accounts} onDone={refreshAccounts} />}
            {tab === 'activity'  && <ActivityTab accounts={accounts} />}
            {tab === 'jobs'      && <JobsTab />}
            {tab === 'audit'     && <AuditTab />}
            {tab === 'system'    && <SystemTab />}
            {tab === 'settings'  && <SettingsTab />}
            </Suspense>
          </div>
        </main>
      </div>

      {addOpen && (
        <Suspense fallback={<LazyFallback />}>
        <AddAccountModal
          onClose={() => setAddOpen(false)}
          onAdded={() => { setAddOpen(false); refreshAccounts(); refreshStats() }}
          onImported={() => { refreshAccounts(); refreshStats() }}
        />
        </Suspense>
      )}
    </div>
  )
}

function LazyFallback() {
  return <div className="nb-card-sm p-4 font-bold uppercase tracking-tight">Đang tải mô-đun…</div>
}
