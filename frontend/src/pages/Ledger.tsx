import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatMoney, formatQty, newIdempotencyKey } from '../api'
import type { BusinessOut, TransactionOut } from '../types'

interface LedgerPageProps {
  business: BusinessOut
}

function getTodayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export function LedgerPage({ business }: LedgerPageProps) {
  const queryClient = useQueryClient()

  const [filterType, setFilterType] = useState<string>('')
  const [unpaidOnly, setUnpaidOnly] = useState(false)

  // New transaction state
  const [txType, setTxType] = useState<'sale' | 'purchase' | 'expense'>('sale')
  const [partyId, setPartyId] = useState<string>('')
  const [productId, setProductId] = useState<string>('')
  const [qty, setQty] = useState('1')
  const [unitPrice, setUnitPrice] = useState('')
  const [expenseAmount, setExpenseAmount] = useState('')
  const [discount, setDiscount] = useState('0')
  const [paidAmount, setPaidAmount] = useState('0')
  const [txDate, setTxDate] = useState(getTodayIso)
  const [dueDate, setDueDate] = useState('')
  const [notes, setNotes] = useState('')

  // Opening cash modal
  const [showOpeningCash, setShowOpeningCash] = useState(false)
  const [openingCashAmount, setOpeningCashAmount] = useState('0')
  const [openingCashDate, setOpeningCashDate] = useState(getTodayIso)

  // Payment modal
  const [payingTx, setPayingTx] = useState<TransactionOut | null>(null)
  const [paymentAmount, setPaymentAmount] = useState('')
  const [paymentDate, setPaymentDate] = useState(getTodayIso)
  const [paymentNote, setPaymentNote] = useState('')

  const txQuery = useQuery({
    queryKey: ['transactions', filterType, unpaidOnly],
    queryFn: () =>
      api.listTransactions({
        type: filterType || undefined,
        unpaidOnly,
      }),
  })
  const customersQuery = useQuery({ queryKey: ['customers'], queryFn: api.listCustomers })
  const suppliersQuery = useQuery({ queryKey: ['suppliers'], queryFn: api.listSuppliers })
  const productsQuery = useQuery({ queryKey: ['products'], queryFn: api.listProducts })

  const createTxMutation = useMutation({
    mutationFn: () =>
      api.createTransaction({
        type: txType,
        customer_id: txType === 'sale' && partyId ? partyId : null,
        supplier_id: txType === 'purchase' && partyId ? partyId : null,
        date: txDate,
        due_date: dueDate || null,
        discount,
        paid_amount: paidAmount || '0',
        expense_amount: txType === 'expense' ? expenseAmount : null,
        idempotency_key: newIdempotencyKey('tx'),
        notes: notes.trim() || null,
        items:
          txType === 'expense'
            ? []
            : [
                {
                  product_id: productId || null,
                  qty,
                  unit_price: unitPrice ? unitPrice : null,
                },
              ],
      }),
    onSuccess: () => {
      setNotes('')
      setUnitPrice('')
      setExpenseAmount('')
      void queryClient.invalidateQueries()
    },
  })

  const openingCashMutation = useMutation({
    mutationFn: () =>
      api.setOpeningCash({
        amount: openingCashAmount,
        date: openingCashDate,
      }),
    onSuccess: () => {
      setShowOpeningCash(false)
      void queryClient.invalidateQueries()
    },
  })

  const paymentMutation = useMutation({
    mutationFn: () => {
      if (!payingTx) throw new Error('No transaction selected')
      return api.recordPayment(payingTx.id, {
        amount: paymentAmount,
        date: paymentDate,
        idempotency_key: newIdempotencyKey('pay'),
        note: paymentNote.trim() || undefined,
      })
    },
    onSuccess: () => {
      setPayingTx(null)
      setPaymentAmount('')
      setPaymentNote('')
      void queryClient.invalidateQueries()
    },
  })

  return (
    <div className="space-y-6 cp-enter">
      {/* Header + Opening Cash */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Ledger</h1>
          <p className="text-sm text-slate-500">
            Post sales, purchases, expenses, and partial payments with server-verified balances.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowOpeningCash(true)}
          className="cp-btn min-h-[40px] px-4 py-2 rounded-xl glass-panel text-sm font-medium text-[#0d7480] hover:text-[#0a5c66]"
        >
          Set opening cash
        </button>
      </div>

      {/* Create Transaction Form */}
      <section className="glass-panel rounded-3xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-900">Record entry</h2>
          <div className="flex rounded-xl bg-slate-900/[0.05] p-1">
            {(['sale', 'purchase', 'expense'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  setTxType(t)
                  setPartyId('')
                }}
                className={`cp-btn px-3.5 py-1.5 rounded-lg text-xs font-medium capitalize ${
                  txType === t ? 'bg-[#13252f] text-white' : 'text-slate-600'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <form
          className="mt-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            createTxMutation.mutate()
          }}
        >
          {txType !== 'expense' && (
            <>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  {txType === 'sale' ? 'Customer' : 'Supplier'}
                </span>
                <select
                  value={partyId}
                  onChange={(e) => setPartyId(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">
                    {txType === 'sale' ? 'Walk-in / cash sale' : 'Select supplier'}
                  </option>
                  {(txType === 'sale' ? customersQuery.data : suppliersQuery.data)?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block text-xs">
                <span className="font-medium text-slate-700">Product</span>
                <select
                  required
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">Select product...</option>
                  {productsQuery.data?.map((prod) => (
                    <option key={prod.id} value={prod.id}>
                      {prod.name} ({prod.sku})
                    </option>
                  ))}
                </select>
              </label>

              <label className="block text-xs">
                <span className="font-medium text-slate-700">Quantity</span>
                <input
                  type="number"
                  required
                  min="0.0001"
                  step="any"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
                />
              </label>

              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Unit price (optional, defaults from catalog)
                </span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="Default"
                  value={unitPrice}
                  onChange={(e) => setUnitPrice(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
                />
              </label>
            </>
          )}

          {txType === 'expense' && (
            <label className="block text-xs">
              <span className="font-medium text-slate-700">
                Expense amount ({business.currency})
              </span>
              <input
                type="number"
                required
                min="0.01"
                step="0.01"
                value={expenseAmount}
                onChange={(e) => setExpenseAmount(e.target.value)}
                className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
              />
            </label>
          )}

          <label className="block text-xs">
            <span className="font-medium text-slate-700">Paid now ({business.currency})</span>
            <input
              type="number"
              required
              min="0"
              step="0.01"
              value={paidAmount}
              onChange={(e) => setPaidAmount(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
            />
          </label>

          {txType !== 'expense' && (
            <label className="block text-xs">
              <span className="font-medium text-slate-700">Discount ({business.currency})</span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={discount}
                onChange={(e) => setDiscount(e.target.value)}
                className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
              />
            </label>
          )}

          <label className="block text-xs">
            <span className="font-medium text-slate-700">Date</span>
            <input
              type="date"
              required
              value={txDate}
              onChange={(e) => setTxDate(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-xs">
            <span className="font-medium text-slate-700">Due date (optional for credit)</span>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-xs sm:col-span-2 lg:col-span-3">
            <span className="font-medium text-slate-700">Notes</span>
            <input
              type="text"
              placeholder="Optional description"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
            />
          </label>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={createTxMutation.isPending}
              className="cp-btn w-full min-h-[40px] rounded-xl bg-[#0d7480] text-white text-sm font-medium hover:bg-[#0a5c66] disabled:opacity-60"
            >
              {createTxMutation.isPending ? 'Posting...' : `Post ${txType}`}
            </button>
          </div>
        </form>

        {createTxMutation.isError && (
          <p className="mt-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-xl p-2.5">
            {createTxMutation.error.message}
          </p>
        )}
      </section>

      {/* Transactions Table */}
      <section className="glass-panel rounded-3xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-900">Posted transactions</h2>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="cp-input rounded-xl px-3 py-1.5 text-xs"
            >
              <option value="">All types</option>
              <option value="sale">Sales</option>
              <option value="purchase">Purchases</option>
              <option value="expense">Expenses</option>
              <option value="sale_return">Sale returns</option>
              <option value="purchase_return">Purchase returns</option>
            </select>
            <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-700 px-2">
              <input
                type="checkbox"
                checked={unpaidOnly}
                onChange={(e) => setUnpaidOnly(e.target.checked)}
                className="rounded border-slate-300"
              />
              Unpaid only
            </label>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-900/10 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2.5 pr-4">Date</th>
                <th className="py-2.5 pr-4">Type</th>
                <th className="py-2.5 pr-4">Notes / Items</th>
                <th className="py-2.5 pr-4 text-right">Total</th>
                <th className="py-2.5 pr-4 text-right">Paid</th>
                <th className="py-2.5 pr-4 text-right">Balance due</th>
                <th className="py-2.5 pr-4">Due date</th>
                <th className="py-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-900/8">
              {txQuery.data?.map((tx) => {
                const unpaid = Number(tx.balance_due) > 0
                const canPay =
                  unpaid && (tx.type === 'sale' || tx.type === 'purchase' || tx.type === 'expense')
                return (
                  <tr key={tx.id} className="hover:bg-white/40">
                    <td className="py-3 pr-4 tabular-nums text-xs text-slate-600">{tx.date}</td>
                    <td className="py-3 pr-4">
                      <span className="inline-block px-2 py-0.5 rounded-md text-xs font-medium capitalize bg-slate-900/[0.06] text-slate-800">
                        {tx.type.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-xs text-slate-700 max-w-xs truncate">
                      {tx.notes || `${tx.items.length} item(s) · ${formatQty(tx.items[0]?.qty ?? '0')}`}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums font-medium">
                      {formatMoney(tx.total, business.currency)}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums text-slate-600">
                      {formatMoney(tx.amount_paid, business.currency)}
                    </td>
                    <td
                      className={`py-3 pr-4 text-right tabular-nums font-medium ${
                        unpaid ? 'text-amber-700' : 'text-slate-400'
                      }`}
                    >
                      {formatMoney(tx.balance_due, business.currency)}
                    </td>
                    <td className="py-3 pr-4 text-xs text-slate-500 tabular-nums">
                      {tx.due_date ?? '—'}
                    </td>
                    <td className="py-3 text-right">
                      {canPay && (
                        <button
                          type="button"
                          onClick={() => {
                            setPayingTx(tx)
                            setPaymentAmount(String(Number(tx.balance_due)))
                          }}
                          className="cp-btn px-3 py-1 rounded-lg bg-[#0d7480] text-white text-xs font-medium hover:bg-[#0a5c66]"
                        >
                          Record payment
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {txQuery.data?.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-sm text-slate-500">
                    No transactions recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Opening Cash Modal */}
      {showOpeningCash && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="glass-panel cp-enter w-full max-w-sm rounded-2xl p-6 bg-white/90">
            <h3 className="text-base font-semibold text-slate-900">Set Opening Cash</h3>
            <p className="text-xs text-slate-500 mt-1">
              Upserts your business opening cash balance without double-counting.
            </p>
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                openingCashMutation.mutate()
              }}
            >
              <label className="block text-xs">
                <span className="font-medium text-slate-700">Amount ({business.currency})</span>
                <input
                  type="number"
                  required
                  min="0"
                  step="0.01"
                  value={openingCashAmount}
                  onChange={(e) => setOpeningCashAmount(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">As of date</span>
                <input
                  type="date"
                  required
                  value={openingCashDate}
                  onChange={(e) => setOpeningCashDate(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                />
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowOpeningCash(false)}
                  className="cp-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={openingCashMutation.isPending}
                  className="cp-btn px-4 py-1.5 rounded-xl bg-[#0d7480] text-white text-xs font-medium"
                >
                  Save opening cash
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Record Payment Modal */}
      {payingTx && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="glass-panel cp-enter w-full max-w-sm rounded-2xl p-6 bg-white/90">
            <h3 className="text-base font-semibold text-slate-900">Record Payment</h3>
            <p className="text-xs text-slate-500 mt-1">
              Remaining balance: {formatMoney(payingTx.balance_due, business.currency)}
            </p>
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                paymentMutation.mutate()
              }}
            >
              <label className="block text-xs">
                <span className="font-medium text-slate-700">Amount ({business.currency})</span>
                <input
                  type="number"
                  required
                  min="0.01"
                  step="0.01"
                  value={paymentAmount}
                  onChange={(e) => setPaymentAmount(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">Payment date</span>
                <input
                  type="date"
                  required
                  value={paymentDate}
                  onChange={(e) => setPaymentDate(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">Note</span>
                <input
                  type="text"
                  value={paymentNote}
                  onChange={(e) => setPaymentNote(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                />
              </label>
              {paymentMutation.isError && (
                <p className="text-xs text-red-700">{paymentMutation.error.message}</p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setPayingTx(null)}
                  className="cp-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={paymentMutation.isPending}
                  className="cp-btn px-4 py-1.5 rounded-xl bg-[#0d7480] text-white text-xs font-medium"
                >
                  {paymentMutation.isPending ? 'Recording...' : 'Confirm payment'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
