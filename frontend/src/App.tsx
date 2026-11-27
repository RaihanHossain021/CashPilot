import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from './api'

function App() {
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: false,
  })

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">CashPilot</h1>
            <p className="text-sm text-slate-500">Phase 0 Environment Check</p>
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Recheck
          </button>
        </div>

        <div className="mt-6 rounded-lg bg-slate-50 p-4 border border-slate-200 text-sm">
          {isLoading ? (
            <p className="text-slate-600">Checking backend `/health`...</p>
          ) : error ? (
            <div className="text-red-700">
              <p className="font-medium">Backend / Database Unavailable</p>
              <p className="mt-1 text-xs break-words">{error.message}</p>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="font-medium text-emerald-700">Backend &amp; Database Connected</p>
              <p className="text-slate-600">Status: {data?.status}</p>
              <p className="text-slate-600">Database: {data?.database}</p>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}

export default App
