import type { ReactNode } from 'react'
import type { BusinessOut } from '../types'

export type NavTab = 'dashboard' | 'ledger' | 'parties' | 'inventory' | 'advisor' | 'scenarios'

interface AppShellProps {
  business: BusinessOut
  activeTab: NavTab
  onSelectTab: (tab: NavTab) => void
  onOpenSettings: () => void
  onSignOut: () => void
  children: ReactNode
}

const NAV_ITEMS: Array<{ id: NavTab; label: string; soon?: boolean }> = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'ledger', label: 'Ledger' },
  { id: 'parties', label: 'Parties' },
  { id: 'inventory', label: 'Inventory' },
  { id: 'advisor', label: 'Advisor' },
  { id: 'scenarios', label: 'Scenario Lab', soon: true },
]

export function AppShell({
  business,
  activeTab,
  onSelectTab,
  onOpenSettings,
  onSignOut,
  children,
}: AppShellProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 px-4 sm:px-6 pt-3">
        <div className="mx-auto max-w-7xl glass-panel rounded-2xl px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-[#0d7480] text-white flex items-center justify-center font-semibold text-sm shadow-sm">
              CP
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold tracking-tight text-slate-900">CashPilot</span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-teal-900/10 text-[#0d7480]">
                  {business.name}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                {business.vertical} · {business.currency} · Reserve{' '}
                <span className="tabular-nums font-medium">
                  {Number(business.min_cash_reserve).toLocaleString()}
                </span>
              </p>
            </div>
          </div>

          <nav
            aria-label="Primary navigation"
            className="flex items-center gap-1 rounded-xl bg-slate-900/[0.04] p-1 overflow-x-auto max-w-full"
          >
            {NAV_ITEMS.map((item) => {
              const active = activeTab === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectTab(item.id)}
                  aria-current={active ? 'page' : undefined}
                  className={`cp-btn min-h-[38px] px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap flex items-center gap-1.5 ${
                    active
                      ? 'bg-[#13252f] text-white shadow-sm'
                      : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                  }`}
                >
                  <span>{item.label}</span>
                  {item.soon && (
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-md ${
                        active ? 'bg-white/20 text-white' : 'bg-slate-900/8 text-slate-500'
                      }`}
                    >
                      Next
                    </span>
                  )}
                </button>
              )
            })}
          </nav>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenSettings}
              className="cp-btn min-h-[38px] px-3 py-1.5 rounded-xl text-sm font-medium glass-panel-soft text-slate-700 hover:text-slate-900"
            >
              Settings
            </button>
            <button
              type="button"
              onClick={onSignOut}
              className="cp-btn min-h-[38px] px-3 py-1.5 rounded-xl text-sm font-medium text-slate-600 hover:text-red-700 hover:bg-red-50/70"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-7xl px-4 sm:px-6 py-6">{children}</main>
    </div>
  )
}
