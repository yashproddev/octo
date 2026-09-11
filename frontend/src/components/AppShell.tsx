import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Health } from '../types'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/upload', label: 'Upload Dataset' },
  { to: '/decisions', label: 'Decision Log' },
]

function HealthDot() {
  const [health, setHealth] = useState<Health | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api.get<Health>('/health').then(setHealth).catch(() => setFailed(true))
  }, [])

  const pending = !health && !failed
  const ok = health?.database.connected === true
  const color = pending ? 'bg-teal-600' : ok ? 'bg-teal-400' : 'bg-red-500'
  const label = pending
    ? 'Checking…'
    : failed
      ? 'API unreachable'
      : ok
        ? 'Database connected'
        : 'Database unreachable'

  return (
    <div className="flex items-center gap-2 text-xs text-teal-200/80">
      <span className={`size-1.5 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  )
}

export default function AppShell() {
  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col bg-teal-900 px-4 py-5">
        <div className="px-2">
          <div className="text-sm font-semibold tracking-tight text-white">OctoProc</div>
          <div className="mt-0.5 text-xs text-teal-300">M4 · Vendor Reconciliation</div>
        </div>

        <nav className="mt-7 flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-teal-800 font-medium text-white'
                    : 'text-teal-100/80 hover:bg-teal-800/50 hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto border-t border-teal-800 px-2 pt-4">
          <HealthDot />
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-7xl px-8 py-7">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
