import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { BusinessOut } from '../types'

interface SettingsModalProps {
  business: BusinessOut
  onClose: () => void
  onUpdated: (biz: BusinessOut) => void
}

export function SettingsModal({ business, onClose, onUpdated }: SettingsModalProps) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(business.name)
  const [currency, setCurrency] = useState(business.currency)
  const [reserve, setReserve] = useState(String(Number(business.min_cash_reserve)))
  const [slowDays, setSlowDays] = useState(String(business.slow_stock_days_threshold))

  const mutation = useMutation({
    mutationFn: () =>
      api.updateBusiness({
        name: name.trim(),
        currency: currency.trim().toUpperCase(),
        min_cash_reserve: reserve,
        slow_stock_days_threshold: Number(slowDays),
      }),
    onSuccess: (updated) => {
      onUpdated(updated)
      void queryClient.invalidateQueries()
      onClose()
    },
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <div className="glass-panel cp-enter w-full max-w-md rounded-2xl p-6 bg-white/90">
        <div className="flex items-center justify-between">
          <div>
            <h2 id="settings-title" className="text-lg font-semibold text-slate-900">
              Business Settings
            </h2>
            <p className="text-xs text-slate-500">
              Adjust your currency, minimum cash safety reserve, and slow-stock threshold.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="cp-btn rounded-lg px-2.5 py-1 text-sm text-slate-500 hover:bg-slate-100"
          >
            Close
          </button>
        </div>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate()
          }}
        >
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Business name</span>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Currency</span>
              <input
                type="text"
                required
                maxLength={12}
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm uppercase"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Slow-stock threshold (days)</span>
              <input
                type="number"
                required
                min={1}
                max={365}
                value={slowDays}
                onChange={(e) => setSlowDays(e.target.value)}
                className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
              />
            </label>
          </div>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">Minimum cash reserve</span>
            <input
              type="number"
              required
              min={0}
              step="0.01"
              value={reserve}
              onChange={(e) => setReserve(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
            />
          </label>

          {mutation.isError && (
            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-xl p-2.5">
              {mutation.error.message}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="cp-btn rounded-xl px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="cp-btn rounded-xl px-4 py-2 text-sm font-medium bg-[#0d7480] text-white hover:bg-[#0a5c66] disabled:opacity-60"
            >
              {mutation.isPending ? 'Saving...' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
