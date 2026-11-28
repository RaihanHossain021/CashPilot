import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, setStoredToken } from '../api'
import type { BusinessOut } from '../types'

interface AuthPageProps {
  needsBusinessSetup: boolean
  onAuthenticated: () => void
  onBusinessCreated: (biz: BusinessOut) => void
  onSignOut: () => void
}

export function AuthPage({
  needsBusinessSetup,
  onAuthenticated,
  onBusinessCreated,
  onSignOut,
}: AuthPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')

  // Onboarding state
  const [bizName, setBizName] = useState('')
  const [vertical, setVertical] = useState<'grocery' | 'service' | 'other'>('grocery')
  const [currency, setCurrency] = useState('BDT')
  const [reserve, setReserve] = useState('15000')

  const authMutation = useMutation({
    mutationFn: async () => {
      if (mode === 'login') {
        return api.login({ email, password })
      }
      return api.register({ email, password, name: fullName })
    },
    onSuccess: (res) => {
      setStoredToken(res.access_token)
      onAuthenticated()
    },
  })

  const demoMutation = useMutation({
    mutationFn: async () => {
      const seed = await api.seedDemo()
      return api.login({ email: seed.demo_email, password: seed.demo_password })
    },
    onSuccess: (res) => {
      setStoredToken(res.access_token)
      onAuthenticated()
    },
  })

  const businessMutation = useMutation({
    mutationFn: () =>
      api.createBusiness({
        name: bizName,
        vertical,
        currency,
        min_cash_reserve: reserve,
        slow_stock_days_threshold: 45,
      }),
    onSuccess: (biz) => {
      onBusinessCreated(biz)
    },
  })

  if (needsBusinessSetup) {
    return (
      <main className="min-h-screen flex items-center justify-center p-4 sm:p-6">
        <div className="glass-panel cp-enter w-full max-w-lg rounded-3xl p-7 sm:p-8">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#0d7480]">
              Step 2 of 2 · Business Profile
            </span>
            <button
              type="button"
              onClick={onSignOut}
              className="cp-btn text-xs font-medium text-slate-500 hover:text-slate-900"
            >
              Sign out
            </button>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
            Set up your business ledger
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Tell CashPilot your currency and safety reserve so forecasts flag cash gaps accurately.
          </p>

          <form
            className="mt-6 space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              businessMutation.mutate()
            }}
          >
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Business name</span>
              <input
                type="text"
                required
                placeholder="e.g. Green Valley Grocery"
                value={bizName}
                onChange={(e) => setBizName(e.target.value)}
                className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm"
              />
            </label>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label className="block text-sm">
                <span className="font-medium text-slate-700">Vertical</span>
                <select
                  value={vertical}
                  onChange={(e) => setVertical(e.target.value as 'grocery' | 'service' | 'other')}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2.5 text-sm"
                >
                  <option value="grocery">Grocery</option>
                  <option value="service">Service</option>
                  <option value="other">Other</option>
                </select>
              </label>

              <label className="block text-sm">
                <span className="font-medium text-slate-700">Currency</span>
                <input
                  type="text"
                  required
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm uppercase"
                />
              </label>

              <label className="block text-sm">
                <span className="font-medium text-slate-700">Min cash reserve</span>
                <input
                  type="number"
                  required
                  min={0}
                  value={reserve}
                  onChange={(e) => setReserve(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm tabular-nums"
                />
              </label>
            </div>

            {businessMutation.isError && (
              <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
                {businessMutation.error.message}
              </p>
            )}

            <button
              type="submit"
              disabled={businessMutation.isPending}
              className="cp-btn w-full min-h-[44px] rounded-xl bg-[#0d7480] text-white text-sm font-medium hover:bg-[#0a5c66] disabled:opacity-60"
            >
              {businessMutation.isPending ? 'Creating business...' : 'Create business workspace'}
            </button>
          </form>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4 sm:p-6">
      <div className="mx-auto w-full max-w-5xl grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        <section className="lg:col-span-7 glass-slate cp-enter rounded-3xl p-8 sm:p-10 text-white flex flex-col justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-teal-200 border border-white/10">
              CashPilot · Finance-First Copilot
            </div>
            <h1 className="mt-5 text-3xl sm:text-4xl font-semibold tracking-tight leading-tight">
              See real cash, catch gaps early, unlock trapped stock capital.
            </h1>
            <p className="mt-4 text-sm sm:text-base text-slate-300 leading-relaxed max-w-xl">
              Every balance, cash-gap forecast, and financial-readiness signal is computed
              deterministically from your business records—no invented numbers and no opaque credit
              scoring.
            </p>
          </div>

          <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-2xl bg-white/[0.06] border border-white/10 p-4">
              <p className="text-xs text-slate-300">Cash-Flow Radar</p>
              <p className="mt-1 text-sm font-medium text-white">14 &amp; 30-day gap detection</p>
            </div>
            <div className="rounded-2xl bg-white/[0.06] border border-white/10 p-4">
              <p className="text-xs text-slate-300">Slow Stock Capital</p>
              <p className="mt-1 text-sm font-medium text-white">Flagged before borrowing</p>
            </div>
            <div className="rounded-2xl bg-white/[0.06] border border-white/10 p-4">
              <p className="text-xs text-slate-300">Readiness Profile</p>
              <p className="mt-1 text-sm font-medium text-white">Transparent green/amber/red</p>
            </div>
          </div>
        </section>

        <section className="lg:col-span-5 glass-panel cp-enter rounded-3xl p-7 sm:p-8 flex flex-col justify-between">
          <div>
            <div className="flex rounded-xl bg-slate-900/[0.05] p-1">
              <button
                type="button"
                onClick={() => setMode('login')}
                className={`cp-btn flex-1 py-2 rounded-lg text-sm font-medium ${
                  mode === 'login' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'
                }`}
              >
                Sign in
              </button>
              <button
                type="button"
                onClick={() => setMode('register')}
                className={`cp-btn flex-1 py-2 rounded-lg text-sm font-medium ${
                  mode === 'register' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'
                }`}
              >
                Create account
              </button>
            </div>

            <form
              className="mt-6 space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                authMutation.mutate()
              }}
            >
              {mode === 'register' && (
                <label className="block text-sm">
                  <span className="font-medium text-slate-700">Your name</span>
                  <input
                    type="text"
                    required
                    placeholder="Tariq Rahman"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm"
                  />
                </label>
              )}

              <label className="block text-sm">
                <span className="font-medium text-slate-700">Email</span>
                <input
                  type="email"
                  required
                  placeholder="merchant@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm"
                />
              </label>

              <label className="block text-sm">
                <span className="font-medium text-slate-700">Password</span>
                <input
                  type="password"
                  required
                  minLength={mode === 'register' ? 8 : 1}
                  placeholder="Minimum 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3.5 py-2.5 text-sm"
                />
              </label>

              {authMutation.isError && (
                <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
                  {authMutation.error.message}
                </p>
              )}

              <button
                type="submit"
                disabled={authMutation.isPending}
                className="cp-btn w-full min-h-[44px] rounded-xl bg-[#0d7480] text-white text-sm font-medium hover:bg-[#0a5c66] disabled:opacity-60"
              >
                {authMutation.isPending
                  ? 'Please wait...'
                  : mode === 'login'
                    ? 'Sign in to CashPilot'
                    : 'Register & continue'}
              </button>
            </form>
          </div>

          <div className="mt-6 pt-5 border-t border-slate-900/10">
            <p className="text-xs text-slate-500">Exploring in development mode?</p>
            <button
              type="button"
              onClick={() => demoMutation.mutate()}
              disabled={demoMutation.isPending}
              className="cp-btn mt-2 w-full min-h-[44px] rounded-xl glass-panel-soft text-sm font-medium text-[#0d7480] hover:bg-white/90 disabled:opacity-60"
            >
              {demoMutation.isPending
                ? 'Seeding FreshBasket Mart...'
                : 'Load FreshBasket Mart Demo'}
            </button>
            {demoMutation.isError && (
              <p className="mt-2 text-xs text-red-700">{demoMutation.error.message}</p>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}
