import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatMoney } from '../api'

export function PartiesPage() {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<'customer' | 'supplier'>('customer')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')

  const partiesQuery = useQuery({
    queryKey: ['parties-balances'],
    queryFn: api.getPartiesBalances,
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const payload = { name: name.trim(), phone: phone.trim() || null }
      return kind === 'customer' ? api.createCustomer(payload) : api.createSupplier(payload)
    },
    onSuccess: () => {
      setName('')
      setPhone('')
      void queryClient.invalidateQueries({ queryKey: ['parties-balances'] })
      void queryClient.invalidateQueries({ queryKey: ['customers'] })
      void queryClient.invalidateQueries({ queryKey: ['suppliers'] })
    },
  })

  const data = partiesQuery.data
  const activeList = kind === 'customer' ? (data?.customers ?? []) : (data?.suppliers ?? [])
  const currency = data?.currency ?? ''

  return (
    <div className="space-y-6 cp-enter">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Parties</h1>
          <p className="text-sm text-slate-500">
            Customers who owe you and suppliers you owe, with backend-verified overdue balances.
          </p>
        </div>
        <div className="flex rounded-xl bg-slate-900/[0.05] p-1">
          <button
            type="button"
            onClick={() => setKind('customer')}
            className={`cp-btn px-4 py-1.5 rounded-lg text-sm font-medium ${
              kind === 'customer' ? 'bg-[#13252f] text-white' : 'text-slate-600'
            }`}
          >
            Customers ({data?.customers.length ?? 0})
          </button>
          <button
            type="button"
            onClick={() => setKind('supplier')}
            className={`cp-btn px-4 py-1.5 rounded-lg text-sm font-medium ${
              kind === 'supplier' ? 'bg-[#13252f] text-white' : 'text-slate-600'
            }`}
          >
            Suppliers ({data?.suppliers.length ?? 0})
          </button>
        </div>
      </div>

      {/* Add Party */}
      <section className="glass-panel rounded-3xl p-6">
        <h2 className="text-base font-semibold text-slate-900">
          Add {kind === 'customer' ? 'customer' : 'supplier'}
        </h2>
        <form
          className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            createMutation.mutate()
          }}
        >
          <input
            type="text"
            required
            placeholder={kind === 'customer' ? 'Customer name' : 'Supplier name'}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="cp-input rounded-xl px-3.5 py-2.5 text-sm"
          />
          <input
            type="text"
            placeholder="Phone (optional)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="cp-input rounded-xl px-3.5 py-2.5 text-sm"
          />
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="cp-btn min-h-[42px] rounded-xl bg-[#0d7480] text-white text-sm font-medium hover:bg-[#0a5c66]"
          >
            {createMutation.isPending ? 'Adding...' : `Add ${kind}`}
          </button>
        </form>
      </section>

      {/* Party List */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {activeList.map((party) => {
          const hasOverdue = Number(party.overdue_amount) > 0
          return (
            <article key={party.id} className="glass-panel cp-card-lift rounded-2xl p-5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-slate-900">{party.name}</h3>
                  <p className="text-xs text-slate-500">{party.phone ?? 'No phone on file'}</p>
                </div>
                {hasOverdue && (
                  <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-red-500/12 text-red-700 border border-red-500/25">
                    Overdue
                  </span>
                )}
              </div>

              <div className="mt-4 pt-3 border-t border-slate-900/8 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-slate-500">
                    {kind === 'customer' ? 'Owes you' : 'You owe'}
                  </p>
                  <p className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                    {formatMoney(party.balance_due, currency)}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500">Overdue</p>
                  <p
                    className={`mt-0.5 text-base font-semibold tabular-nums ${
                      hasOverdue ? 'text-red-700' : 'text-slate-400'
                    }`}
                  >
                    {formatMoney(party.overdue_amount, currency)}
                  </p>
                </div>
              </div>
              {party.earliest_due_date && (
                <p className="mt-2 text-[11px] text-slate-500">
                  Earliest due date: {party.earliest_due_date}
                </p>
              )}
            </article>
          )
        })}
      </section>
    </div>
  )
}
