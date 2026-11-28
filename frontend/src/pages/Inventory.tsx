import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatMoney, formatQty } from '../api'

export function InventoryPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [sku, setSku] = useState('')
  const [unit, setUnit] = useState('pcs')
  const [salePrice, setSalePrice] = useState('0')
  const [avgCost, setAvgCost] = useState('0')
  const [reorderLevel, setReorderLevel] = useState('5')

  const [stockProdId, setStockProdId] = useState('')
  const [openingQty, setOpeningQty] = useState('')
  const [openingCost, setOpeningCost] = useState('')

  const invQuery = useQuery({
    queryKey: ['inventory'],
    queryFn: api.getInventory,
  })

  const createProductMutation = useMutation({
    mutationFn: () =>
      api.createProduct({
        name: name.trim(),
        sku: sku.trim(),
        kind: 'goods',
        unit: unit.trim(),
        track_inventory: true,
        reorder_level: reorderLevel,
        sale_price: salePrice,
        avg_cost: avgCost,
      }),
    onSuccess: () => {
      setName('')
      setSku('')
      void queryClient.invalidateQueries()
    },
  })

  const openingStockMutation = useMutation({
    mutationFn: () =>
      api.setOpeningStock({
        product_id: stockProdId,
        qty: openingQty,
        unit_cost: openingCost,
        date: new Date().toISOString().slice(0, 10),
      }),
    onSuccess: () => {
      setStockProdId('')
      setOpeningQty('')
      setOpeningCost('')
      void queryClient.invalidateQueries()
    },
  })

  const inv = invQuery.data

  return (
    <div className="space-y-6 cp-enter">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Inventory</h1>
        <p className="text-sm text-slate-500">
          Stock valuation, sales velocity, days of stock, and capital tied up in slow items.
        </p>
      </div>

      {inv && (
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="glass-panel rounded-2xl p-5">
            <p className="text-xs font-medium text-slate-500">Total stock value</p>
            <p className="mt-1.5 text-xl font-semibold tabular-nums text-slate-900">
              {formatMoney(inv.total_stock_value, inv.currency)}
            </p>
          </div>
          <div className="glass-panel rounded-2xl p-5">
            <p className="text-xs font-medium text-slate-500">Slow-stock value flagged</p>
            <p className="mt-1.5 text-xl font-semibold tabular-nums text-amber-700">
              {formatMoney(inv.slow_stock_value_flagged, inv.currency)}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">
              {Number(inv.slow_stock_pct_of_inventory).toFixed(1)}% of inventory
            </p>
          </div>
          <div className="glass-panel rounded-2xl p-5">
            <p className="text-xs font-medium text-slate-500">Velocity window / threshold</p>
            <p className="mt-1.5 text-xl font-semibold tabular-nums text-[#0d7480]">
              {inv.velocity_window_days}d / ≥ {inv.slow_stock_days_threshold}d
            </p>
            <p className="text-xs text-slate-500 mt-0.5">As of {inv.as_of}</p>
          </div>
        </section>
      )}

      {/* Add Product + Opening Stock */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <section className="lg:col-span-7 glass-panel rounded-3xl p-6">
          <h2 className="text-base font-semibold text-slate-900">Add product</h2>
          <form
            className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              createProductMutation.mutate()
            }}
          >
            <input
              type="text"
              required
              placeholder="Product name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm col-span-2 sm:col-span-2"
            />
            <input
              type="text"
              required
              placeholder="SKU"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm"
            />
            <input
              type="text"
              required
              placeholder="Unit (bag, pcs)"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm"
            />
            <input
              type="number"
              required
              min="0"
              step="0.01"
              placeholder="Sale price"
              value={salePrice}
              onChange={(e) => setSalePrice(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm tabular-nums"
            />
            <input
              type="number"
              required
              min="0"
              step="0.01"
              placeholder="Initial cost"
              value={avgCost}
              onChange={(e) => setAvgCost(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm tabular-nums"
            />
            <input
              type="number"
              required
              min="0"
              step="1"
              placeholder="Reorder level"
              value={reorderLevel}
              onChange={(e) => setReorderLevel(e.target.value)}
              className="cp-input rounded-xl px-3 py-2 text-sm tabular-nums"
            />
            <button
              type="submit"
              disabled={createProductMutation.isPending}
              className="cp-btn col-span-2 rounded-xl bg-[#0d7480] text-white text-sm font-medium py-2 hover:bg-[#0a5c66]"
            >
              Add product
            </button>
          </form>
          {createProductMutation.isError && (
            <p className="mt-2 text-xs text-red-700">{createProductMutation.error.message}</p>
          )}
        </section>

        <section className="lg:col-span-5 glass-panel rounded-3xl p-6">
          <h2 className="text-base font-semibold text-slate-900">Record opening stock</h2>
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              openingStockMutation.mutate()
            }}
          >
            <select
              required
              value={stockProdId}
              onChange={(e) => setStockProdId(e.target.value)}
              className="cp-input w-full rounded-xl px-3 py-2 text-sm"
            >
              <option value="">Select product...</option>
              {inv?.items.map((item) => (
                <option key={item.product_id} value={item.product_id}>
                  {item.name} ({item.sku})
                </option>
              ))}
            </select>
            <div className="grid grid-cols-2 gap-3">
              <input
                type="number"
                required
                min="0.0001"
                step="any"
                placeholder="Qty"
                value={openingQty}
                onChange={(e) => setOpeningQty(e.target.value)}
                className="cp-input rounded-xl px-3 py-2 text-sm tabular-nums"
              />
              <input
                type="number"
                required
                min="0"
                step="0.01"
                placeholder="Unit cost"
                value={openingCost}
                onChange={(e) => setOpeningCost(e.target.value)}
                className="cp-input rounded-xl px-3 py-2 text-sm tabular-nums"
              />
            </div>
            <button
              type="submit"
              disabled={openingStockMutation.isPending}
              className="cp-btn w-full rounded-xl bg-[#13252f] text-white text-sm font-medium py-2"
            >
              Post opening stock
            </button>
          </form>
        </section>
      </div>

      {/* Inventory Table */}
      <section className="glass-panel rounded-3xl p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-900/10 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2.5 pr-4">Product</th>
                <th className="py-2.5 pr-4 text-right">On hand</th>
                <th className="py-2.5 pr-4 text-right">Avg cost</th>
                <th className="py-2.5 pr-4 text-right">Stock value</th>
                <th className="py-2.5 pr-4 text-right">Daily velocity</th>
                <th className="py-2.5 pr-4 text-right">Days of stock</th>
                <th className="py-2.5 text-right">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-900/8">
              {inv?.items.map((item) => (
                <tr key={item.product_id} className="hover:bg-white/40">
                  <td className="py-3 pr-4">
                    <p className="font-medium text-slate-900">{item.name}</p>
                    <p className="text-xs text-slate-500">{item.sku}</p>
                  </td>
                  <td className="py-3 pr-4 text-right tabular-nums">
                    {formatQty(item.on_hand_qty)} {item.unit}
                  </td>
                  <td className="py-3 pr-4 text-right tabular-nums text-slate-600">
                    {formatMoney(item.avg_cost, inv.currency)}
                  </td>
                  <td className="py-3 pr-4 text-right tabular-nums font-medium">
                    {formatMoney(item.stock_value, inv.currency)}
                  </td>
                  <td className="py-3 pr-4 text-right tabular-nums text-slate-600">
                    {formatQty(item.daily_velocity)}/d
                  </td>
                  <td className="py-3 pr-4 text-right tabular-nums">
                    {item.days_of_stock ? `${formatQty(item.days_of_stock)}d` : 'No sales'}
                  </td>
                  <td className="py-3 text-right space-x-1">
                    {item.slow_stock && (
                      <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-800 border border-amber-500/30">
                        Slow capital
                      </span>
                    )}
                    {item.low_stock && (
                      <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-500/15 text-red-700 border border-red-500/30">
                        Low stock
                      </span>
                    )}
                    {!item.slow_stock && !item.low_stock && (
                      <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/12 text-emerald-800">
                        Healthy
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
