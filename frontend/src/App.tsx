import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api, getStoredToken, setStoredToken } from './api'
import { AppShell, type NavTab } from './components/AppShell'
import { SettingsModal } from './components/SettingsModal'
import { AuthPage } from './pages/AuthPage'
import { AdvisorPage } from './pages/Advisor'
import { DashboardPage } from './pages/Dashboard'
import { InventoryPage } from './pages/Inventory'
import { LedgerPage } from './pages/Ledger'
import { PartiesPage } from './pages/Parties'
import { ScenarioLabPage } from './pages/ScenarioLab'
import type { ScenarioRequestPayload } from './types'

function App() {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = useState<boolean>(() => Boolean(getStoredToken()))
  const [activeTab, setActiveTab] = useState<NavTab>('dashboard')
  const [showSettings, setShowSettings] = useState(false)
  const [scenarioPrefill, setScenarioPrefill] = useState<ScenarioRequestPayload | null>(null)
  const [scenarioLaunchKey, setScenarioLaunchKey] = useState(0)

  const businessQuery = useQuery({
    queryKey: ['business'],
    queryFn: api.getBusiness,
    enabled: hasToken,
    retry: false,
  })

  const handleSignOut = () => {
    setStoredToken(null)
    setHasToken(false)
    queryClient.clear()
  }

  if (
    hasToken &&
    businessQuery.isError &&
    businessQuery.error instanceof ApiError &&
    businessQuery.error.status === 401
  ) {
    handleSignOut()
  }

  const needsBusinessSetup =
    hasToken &&
    businessQuery.isError &&
    businessQuery.error instanceof ApiError &&
    businessQuery.error.status === 404

  if (!hasToken || needsBusinessSetup) {
    return (
      <AuthPage
        needsBusinessSetup={needsBusinessSetup}
        onAuthenticated={() => {
          setHasToken(true)
          void queryClient.invalidateQueries({ queryKey: ['business'] })
        }}
        onBusinessCreated={(biz) => {
          queryClient.setQueryData(['business'], biz)
        }}
        onSignOut={handleSignOut}
      />
    )
  }

  if (businessQuery.isLoading || !businessQuery.data) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6">
        <div className="glass-panel rounded-2xl px-6 py-4 text-sm text-slate-600">
          Loading your CashPilot workspace...
        </div>
      </main>
    )
  }

  const business = businessQuery.data

  return (
    <AppShell
      business={business}
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      onOpenSettings={() => setShowSettings(true)}
      onSignOut={handleSignOut}
    >
      {activeTab === 'dashboard' && (
        <DashboardPage
          onOpenScenario={(sc) => {
            setScenarioPrefill(sc)
            setScenarioLaunchKey((k) => k + 1)
            setActiveTab('scenarios')
          }}
        />
      )}
      {activeTab === 'ledger' && <LedgerPage business={business} />}
      {activeTab === 'parties' && <PartiesPage />}
      {activeTab === 'inventory' && <InventoryPage />}
      {activeTab === 'advisor' && <AdvisorPage business={business} />}
      {activeTab === 'scenarios' && (
        <ScenarioLabPage
          key={scenarioLaunchKey}
          business={business}
          prefill={scenarioPrefill}
        />
      )}

      {showSettings && (
        <SettingsModal
          business={business}
          onClose={() => setShowSettings(false)}
          onUpdated={(updated) => queryClient.setQueryData(['business'], updated)}
        />
      )}
    </AppShell>
  )
}

export default App
