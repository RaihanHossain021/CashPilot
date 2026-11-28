import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, formatMoney } from '../api'
import type {
  BusinessOut,
  ScenarioRequestPayload,
  ScenarioResponse,
} from '../types'

interface ScenarioLabPageProps {
  business: BusinessOut
  prefill: ScenarioRequestPayload | null
}

type ScenarioKind = 'collect_dues' | 'delay_payment' | 'reorder_less' | 'planned_purchase'

interface PinnedScenario {
  key: string
  label: string
  color: string
  response: ScenarioResponse
}

const PIN_COLORS = ['#059669', '#2563eb', '#d97706']

function addDaysIso(baseIso: string, days: number): string {
  const [y, m, d] = baseIso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d + days))
  return dt.toISOString().slice(0, 10)
}

function formatSignedMoney(val: string, currency: string): string {
  const num = Number(val)
  const prefix = num > 0 ? '+' : ''
  return `${prefix}${formatMoney(val, currency)}`
}

export function ScenarioLabPage({
  business,
  prefill,
}: ScenarioLabPageProps) {
  const optionsQuery = useQuery({
    queryKey: ['scenario-options'],
    queryFn: api.getScenarioOptions,
  })

  const [fallbackToday] = useState(() => new Date().toISOString().slice(0, 10))
  const [scenarioType, setScenarioType] = useState<ScenarioKind>(() => prefill?.type ?? 'collect_dues')
  const [horizonDays, setHorizonDays] = useState<7 | 14 | 30>(() => prefill?.horizon_days ?? 14)
  const [collectPct, setCollectPct] = useState(() =>
    prefill?.collect_pct ? Number(prefill.collect_pct) : 50,
  )
  const [delayDays, setDelayDays] = useState(() =>
    prefill?.delay_days ? Math.min(prefill.delay_days, prefill.horizon_days) : 7,
  )
  const [reorderPct, setReorderPct] = useState(() =>
    prefill?.reorder_reduction_pct ? Number(prefill.reorder_reduction_pct) : 50,
  )
  const [selectedTxId, setSelectedTxId] = useState<string>(() => prefill?.transaction_id ?? '')
  const [selectedEventId, setSelectedEventId] = useState<string>(
    () => prefill?.scheduled_event_id ?? '',
  )
  const [purchaseAmount, setPurchaseAmount] = useState(() =>
    prefill?.planned_purchase_amount ? String(Number(prefill.planned_purchase_amount)) : '15000',
  )
  const [purchaseDate, setPurchaseDate] = useState<string>(
    () => prefill?.planned_purchase_date ?? addDaysIso(fallbackToday, 3),
  )

  const [lastResult, setLastResult] = useState<ScenarioResponse | null>(null)
  const [pinned, setPinned] = useState<PinnedScenario[]>([])

  const options = optionsQuery.data
  const asOfIso = options?.as_of ?? fallbackToday
  const minPurchaseDate = addDaysIso(asOfIso, 1)
  const maxPurchaseDate = addDaysIso(asOfIso, horizonDays)

  const resolvedTxId = useMemo(() => {
    if (!selectedTxId || !options) return selectedTxId
    const pool = scenarioType === 'collect_dues' ? options.receivables : options.payables
    return pool.some((item) => item.id === selectedTxId) ? selectedTxId : ''
  }, [selectedTxId, options, scenarioType])

  const resolvedEventId = useMemo(() => {
    if (!selectedEventId || !options) return selectedEventId
    return options.reorders.some((item) => item.id === selectedEventId) ? selectedEventId : ''
  }, [selectedEventId, options])

  const prefillNotice = useMemo(() => {
    if (!options) return null
    if (selectedTxId && !resolvedTxId) {
      return 'The recommended invoice/payable is no longer open; switched to default target.'
    }
    if (selectedEventId && !resolvedEventId) {
      return 'The recommended planned reorder is no longer active; switched to default target.'
    }
    return null
  }, [options, selectedTxId, resolvedTxId, selectedEventId, resolvedEventId])

  const handleHorizonChange = (h: 7 | 14 | 30) => {
    setHorizonDays(h)
    if (delayDays > h) setDelayDays(h)
    const nextMax = addDaysIso(asOfIso, h)
    if (purchaseDate < minPurchaseDate || purchaseDate > nextMax) {
      setPurchaseDate(addDaysIso(asOfIso, Math.min(3, h)))
    }
  }

  // Switch off disabled tab if options are empty and user is on an unavailable type
  const availability = useMemo(() => {
    if (!options) {
      return {
        collect_dues: true,
        delay_payment: true,
        reorder_less: true,
        planned_purchase: true,
      }
    }
    return {
      collect_dues: options.receivables.length > 0,
      delay_payment: options.payables.length > 0,
      reorder_less: options.reorders.length > 0 || options.payables.length > 0,
      planned_purchase: true,
    }
  }, [options])

  const requestPayload: ScenarioRequestPayload | null = useMemo(() => {
    if (!availability[scenarioType]) return null
    if (scenarioType === 'collect_dues') {
      return {
        type: 'collect_dues',
        horizon_days: horizonDays,
        collect_pct: String(collectPct),
        transaction_id: resolvedTxId || null,
      }
    }
    if (scenarioType === 'delay_payment') {
      return {
        type: 'delay_payment',
        horizon_days: horizonDays,
        delay_days: Math.min(delayDays, horizonDays),
        transaction_id: resolvedTxId || null,
      }
    }
    if (scenarioType === 'reorder_less') {
      return {
        type: 'reorder_less',
        horizon_days: horizonDays,
        reorder_reduction_pct: String(reorderPct),
        scheduled_event_id: resolvedEventId || null,
      }
    }
    const amtNum = Number(purchaseAmount)
    if (!Number.isFinite(amtNum) || amtNum <= 0) return null
    const clampedDate =
      purchaseDate < minPurchaseDate || purchaseDate > maxPurchaseDate
        ? addDaysIso(asOfIso, Math.min(3, horizonDays))
        : purchaseDate
    return {
      type: 'planned_purchase',
      horizon_days: horizonDays,
      planned_purchase_amount: String(amtNum),
      planned_purchase_date: clampedDate,
    }
  }, [
    availability,
    scenarioType,
    horizonDays,
    collectPct,
    delayDays,
    reorderPct,
    resolvedTxId,
    resolvedEventId,
    purchaseAmount,
    purchaseDate,
    minPurchaseDate,
    maxPurchaseDate,
    asOfIso,
  ])

  const scenarioMutation = useMutation({
    mutationFn: (payload: ScenarioRequestPayload) => api.runScenario(payload),
    onSuccess: (res) => {
      setLastResult(res)
    },
  })

  // Debounce scenario execution (300ms) when controls change
  useEffect(() => {
    if (!options || !requestPayload) return
    const timer = window.setTimeout(() => {
      scenarioMutation.mutate(requestPayload)
    }, 300)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, JSON.stringify(requestPayload)])

  const compareDefaultsMutation = useMutation({
    mutationFn: async () => {
      const calls: Array<{ key: string; label: string; req: ScenarioRequestPayload }> = []
      if (availability.collect_dues) {
        calls.push({
          key: `collect-${horizonDays}`,
          label: 'Collect 50% dues',
          req: { type: 'collect_dues', horizon_days: horizonDays, collect_pct: '50' },
        })
      }
      if (availability.delay_payment) {
        calls.push({
          key: `delay-${horizonDays}`,
          label: `Delay payable ${Math.min(7, horizonDays)}d`,
          req: {
            type: 'delay_payment',
            horizon_days: horizonDays,
            delay_days: Math.min(7, horizonDays),
          },
        })
      }
      if (availability.reorder_less) {
        calls.push({
          key: `reorder-${horizonDays}`,
          label: 'Reorder 50% less',
          req: {
            type: 'reorder_less',
            horizon_days: horizonDays,
            reorder_reduction_pct: '50',
          },
        })
      }
      const results = await Promise.all(
        calls.map(async (c, idx) => ({
          key: c.key,
          label: c.label,
          color: PIN_COLORS[idx % PIN_COLORS.length],
          response: await api.runScenario(c.req),
        })),
      )
      return results
    },
    onSuccess: (items) => {
      setPinned(items.slice(0, 3))
    },
  })

  const handlePinCurrent = () => {
    if (!lastResult) return
    const labelMap: Record<ScenarioKind, string> = {
      collect_dues: `Collect ${collectPct}% dues`,
      delay_payment: `Delay ${Math.min(delayDays, horizonDays)}d`,
      reorder_less: `Reorder -${reorderPct}%`,
      planned_purchase: `Purchase ${formatMoney(purchaseAmount, business.currency)}`,
    }
    const label = labelMap[scenarioType]
    const key = `${scenarioType}-${horizonDays}-${label}`
    setPinned((prev) => {
      const filtered = prev.filter((p) => p.key !== key)
      const next = [
        ...filtered,
        {
          key,
          label,
          color: PIN_COLORS[filtered.length % PIN_COLORS.length],
          response: lastResult,
        },
      ]
      return next.slice(-3)
    })
  }

  const activePinned = useMemo(
    () => pinned.filter((p) => p.response.baseline.horizon_days === horizonDays),
    [pinned, horizonDays],
  )

  // Synchronized chart data (same y-axis scale across baseline, simulated, and pinned)
  const { chartData, yDomain } = useMemo(() => {
    if (!lastResult) return { chartData: [], yDomain: [0, 100] as [number, number] }
    const values: number[] = [Number(lastResult.baseline.min_cash_reserve)]

    const rows = lastResult.baseline.daily.map((bDay, idx) => {
      const simVal = Number(lastResult.simulated.daily[idx]?.closing_cash ?? bDay.closing_cash)
      const baseVal = Number(bDay.closing_cash)
      values.push(baseVal, simVal)

      const row: Record<string, string | number> = {
        date: bDay.date.slice(5),
        baseline: baseVal,
        simulated: simVal,
      }
      activePinned.forEach((pin, pIdx) => {
        const pVal = Number(pin.response.simulated.daily[idx]?.closing_cash ?? baseVal)
        row[`pin_${pIdx}`] = pVal
        values.push(pVal)
      })
      return row
    })

    const minV = Math.min(...values)
    const maxV = Math.max(...values)
    const pad = Math.max(1000, Math.round((maxV - minV) * 0.1))
    return {
      chartData: rows,
      yDomain: [minV - pad, maxV + pad] as [number, number],
    }
  }, [lastResult, activePinned])

  return (
    <div className="space-y-6 cp-enter">
      {/* Top Bar */}
      <section className="glass-panel rounded-3xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Scenario Lab</h1>
            <p className="text-sm text-slate-500">
              Simulate changes against your live baseline without touching ledger records.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => compareDefaultsMutation.mutate()}
              disabled={compareDefaultsMutation.isPending || !options}
              className="cp-btn px-3.5 py-2 rounded-xl bg-[#0d7480]/10 text-[#0d7480] text-xs font-semibold hover:bg-[#0d7480] hover:text-white disabled:opacity-50"
            >
              {compareDefaultsMutation.isPending ? 'Comparing...' : 'Compare defaults side-by-side'}
            </button>
            <div className="flex rounded-xl bg-slate-900/[0.05] p-1">
              {([7, 14, 30] as const).map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => handleHorizonChange(h)}
                  className={`cp-btn px-3 py-1.5 rounded-lg text-xs font-medium ${
                    horizonDays === h ? 'bg-[#13252f] text-white' : 'text-slate-600'
                  }`}
                >
                  {h}d
                </button>
              ))}
            </div>
          </div>
        </div>

        {prefillNotice && (
          <div className="mt-4 rounded-xl bg-amber-50 border border-amber-200 px-3.5 py-2.5 text-xs text-amber-800">
            {prefillNotice}
          </div>
        )}

        {/* Scenario Tabs */}
        <div className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {(
            [
              { id: 'collect_dues', label: 'Collect dues', emptyMsg: 'No overdue customer dues' },
              { id: 'delay_payment', label: 'Delay payment', emptyMsg: 'No open payables' },
              { id: 'reorder_less', label: 'Reorder less', emptyMsg: 'No planned reorders' },
              { id: 'planned_purchase', label: 'Planned purchase', emptyMsg: '' },
            ] as const
          ).map((tab) => {
            const enabled = availability[tab.id]
            const active = scenarioType === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                disabled={!enabled}
                title={!enabled ? tab.emptyMsg : undefined}
                onClick={() => {
                  setScenarioType(tab.id)
                  setSelectedTxId('')
                  setSelectedEventId('')
                }}
                className={`cp-btn p-3 rounded-2xl text-left border ${
                  active
                    ? 'bg-[#13252f] text-white border-[#13252f]'
                    : 'glass-panel-soft text-slate-800 border-slate-900/10'
                } disabled:opacity-45 disabled:cursor-not-allowed`}
              >
                <p className="text-sm font-semibold">{tab.label}</p>
                {!enabled && <p className="text-[11px] text-slate-500 mt-0.5">{tab.emptyMsg}</p>}
              </button>
            )
          })}
        </div>

        {/* Dynamic Parameter Controls */}
        <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
          {scenarioType === 'collect_dues' && (
            <>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Collect overdue percentage: <strong className="tabular-nums">{collectPct}%</strong>
                </span>
                <input
                  type="range"
                  min={10}
                  max={100}
                  step={5}
                  value={collectPct}
                  onChange={(e) => setCollectPct(Number(e.target.value))}
                  className="mt-2 w-full accent-[#0d7480]"
                />
              </label>
              <label className="block text-xs md:col-span-2">
                <span className="font-medium text-slate-700">Target overdue customer invoice</span>
                <select
                  value={selectedTxId}
                  onChange={(e) => setSelectedTxId(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">All overdue customer invoices</option>
                  {options?.receivables.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          {scenarioType === 'delay_payment' && (
            <>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Delay by days (1–{horizonDays}d):{' '}
                  <strong className="tabular-nums">{delayDays}d</strong>
                </span>
                <input
                  type="range"
                  min={1}
                  max={horizonDays}
                  step={1}
                  value={Math.min(delayDays, horizonDays)}
                  onChange={(e) => setDelayDays(Number(e.target.value))}
                  className="mt-2 w-full accent-[#0d7480]"
                />
              </label>
              <label className="block text-xs md:col-span-2">
                <span className="font-medium text-slate-700">Target supplier payable</span>
                <select
                  value={selectedTxId}
                  onChange={(e) => setSelectedTxId(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">Largest upcoming payable in horizon</option>
                  {options?.payables.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          {scenarioType === 'reorder_less' && (
            <>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Reduce reorder by: <strong className="tabular-nums">{reorderPct}%</strong>
                </span>
                <input
                  type="range"
                  min={10}
                  max={100}
                  step={5}
                  value={reorderPct}
                  onChange={(e) => setReorderPct(Number(e.target.value))}
                  className="mt-2 w-full accent-[#0d7480]"
                />
              </label>
              <label className="block text-xs md:col-span-2">
                <span className="font-medium text-slate-700">Target planned reorder</span>
                <select
                  value={selectedEventId}
                  onChange={(e) => setSelectedEventId(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">Default planned reorder in horizon</option>
                  {options?.reorders.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          {scenarioType === 'planned_purchase' && (
            <>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Purchase amount ({business.currency})
                </span>
                <input
                  type="number"
                  min={1}
                  step="100"
                  value={purchaseAmount}
                  onChange={(e) => setPurchaseAmount(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm tabular-nums"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-700">
                  Purchase date ({minPurchaseDate} to {maxPurchaseDate})
                </span>
                <input
                  type="date"
                  min={minPurchaseDate}
                  max={maxPurchaseDate}
                  value={purchaseDate}
                  onChange={(e) => setPurchaseDate(e.target.value)}
                  className="cp-input mt-1 w-full rounded-xl px-3 py-2 text-sm"
                />
              </label>
            </>
          )}
        </div>
      </section>

      {scenarioMutation.isError && (
        <div className="glass-panel rounded-2xl p-4 border-red-200 text-xs text-red-700">
          {scenarioMutation.error.message}
        </div>
      )}

      {/* Results & Comparison Chart */}
      {lastResult && (
        <div
          className={`space-y-6 transition-opacity duration-150 ${
            scenarioMutation.isPending ? 'opacity-60' : 'opacity-100'
          }`}
        >
          {/* Impact Cards */}
          <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs font-medium text-slate-500">Cash impact (Simulated)</p>
              <p
                className={`mt-1.5 text-xl font-semibold tabular-nums ${
                  Number(lastResult.impact.cash_impact) >= 0 ? 'text-emerald-700' : 'text-red-700'
                }`}
              >
                {formatSignedMoney(lastResult.impact.cash_impact, lastResult.currency)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Lowest: {formatMoney(lastResult.simulated.lowest_cash_amount, lastResult.currency)}
              </p>
            </div>

            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs font-medium text-slate-500">Gap reduction vs. reserve</p>
              <p className="mt-1.5 text-xl font-semibold tabular-nums text-[#0d7480]">
                {formatSignedMoney(lastResult.impact.gap_reduction_vs_reserve, lastResult.currency)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Simulated gap:{' '}
                {formatMoney(
                  lastResult.simulated.estimated_cash_gap_vs_reserve,
                  lastResult.currency,
                )}
              </p>
            </div>

            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs font-medium text-slate-500">Breach days change</p>
              <p
                className={`mt-1.5 text-xl font-semibold tabular-nums ${
                  lastResult.impact.breach_days_change <= 0 ? 'text-emerald-700' : 'text-red-700'
                }`}
              >
                {lastResult.impact.breach_days_change > 0
                  ? `+${lastResult.impact.breach_days_change}`
                  : lastResult.impact.breach_days_change}{' '}
                days
              </p>
              {lastResult.impact.affordable_above_reserve !== null && (
                <p
                  className={`mt-1 text-xs font-semibold ${
                    lastResult.impact.affordable_above_reserve
                      ? 'text-emerald-700'
                      : 'text-red-700'
                  }`}
                >
                  {lastResult.impact.affordable_above_reserve
                    ? 'Affordable (stays above reserve)'
                    : 'Not affordable (breaches reserve)'}
                </p>
              )}
            </div>

            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs font-medium text-slate-500">
                Trapped internal capital (Context only)
              </p>
              <p className="mt-1.5 text-xl font-semibold tabular-nums text-slate-900">
                {formatMoney(lastResult.impact.trapped_internal_capital, lastResult.currency)}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">Unchanged by scenario</p>
            </div>
          </section>

          {/* Baseline vs Simulated Chart */}
          <section className="glass-panel rounded-3xl p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  Baseline vs. Simulated Closing Cash ({horizonDays}d)
                </h2>
                <p className="text-xs text-slate-600 mt-0.5">{lastResult.impact.assumption_note}</p>
                {lastResult.impact.affordability_note && (
                  <p className="text-xs text-slate-500 mt-0.5">
                    {lastResult.impact.affordability_note}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {lastResult.impact.moved_beyond_horizon && (
                  <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-800 border border-amber-500/30">
                    Payment moves outside this period
                  </span>
                )}
                <button
                  type="button"
                  onClick={handlePinCurrent}
                  className="cp-btn px-3 py-1.5 rounded-xl glass-panel-soft text-xs font-medium text-[#0d7480] hover:bg-white"
                >
                  Pin to compare ({activePinned.length}/3)
                </button>
                {pinned.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setPinned([])}
                    className="cp-btn px-2.5 py-1.5 rounded-xl text-xs text-slate-500 hover:bg-slate-100"
                  >
                    Clear pins
                  </button>
                )}
              </div>
            </div>

            <div className="mt-4 h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 16, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(19, 37, 47, 0.08)" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#526773' }} />
                  <YAxis domain={yDomain} tick={{ fontSize: 11, fill: '#526773' }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'rgba(255, 255, 255, 0.94)',
                      backdropFilter: 'blur(12px)',
                      borderRadius: '14px',
                      border: '1px solid rgba(19, 37, 47, 0.1)',
                      fontSize: '12px',
                    }}
                    formatter={(val, name) => [
                      formatMoney(String(val ?? 0), lastResult.currency),
                      String(name ?? ''),
                    ]}
                  />
                  <ReferenceLine
                    y={Number(lastResult.baseline.min_cash_reserve)}
                    stroke="#e11d48"
                    strokeDasharray="5 5"
                    label={{ value: 'Min Reserve', fill: '#e11d48', fontSize: 11 }}
                  />
                  <ReferenceLine y={0} stroke="rgba(19, 37, 47, 0.25)" />
                  <Line
                    type="monotone"
                    dataKey="baseline"
                    name="Baseline"
                    stroke="#64748b"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="simulated"
                    name="Simulated (Active)"
                    stroke="#0d7480"
                    strokeWidth={3}
                    dot={false}
                  />
                  {activePinned.map((pin, idx) => (
                    <Line
                      key={pin.key}
                      type="monotone"
                      dataKey={`pin_${idx}`}
                      name={`Simulated: ${pin.label}`}
                      stroke={pin.color}
                      strokeWidth={2}
                      dot={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Side-by-side Pinned Comparison Table */}
          {activePinned.length > 0 && (
            <section className="glass-panel rounded-3xl p-6">
              <h3 className="text-base font-semibold text-slate-900">
                Side-by-Side Pinned Comparison ({horizonDays}d)
              </h3>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-900/10 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">Scenario (Simulated)</th>
                      <th className="py-2 pr-4 text-right">Lowest Cash</th>
                      <th className="py-2 pr-4 text-right">Cash Impact</th>
                      <th className="py-2 pr-4 text-right">Gap vs. Reserve</th>
                      <th className="py-2 pr-4 text-right">Breach Days Δ</th>
                      <th className="py-2">Assumption</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-900/8">
                    {activePinned.map((pin) => (
                      <tr key={pin.key}>
                        <td className="py-2.5 pr-4 font-medium flex items-center gap-2">
                          <span
                            className="h-2.5 w-2.5 rounded-full inline-block"
                            style={{ backgroundColor: pin.color }}
                          />
                          {pin.label}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums">
                          {formatMoney(pin.response.simulated.lowest_cash_amount, lastResult.currency)}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums font-semibold text-[#0d7480]">
                          {formatSignedMoney(pin.response.impact.cash_impact, lastResult.currency)}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums">
                          {formatMoney(
                            pin.response.simulated.estimated_cash_gap_vs_reserve,
                            lastResult.currency,
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums">
                          {pin.response.impact.breach_days_change}
                        </td>
                        <td className="py-2.5 text-xs text-slate-500">
                          {pin.response.impact.assumption_note}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
