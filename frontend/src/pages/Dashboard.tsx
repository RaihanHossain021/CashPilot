import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, formatMoney } from '../api'
import type { ScenarioRequestPayload } from '../types'

interface DashboardPageProps {
  onOpenScenario?: (scenario: ScenarioRequestPayload) => void
}

const STATUS_BADGE: Record<'green' | 'amber' | 'red', string> = {
  green: 'bg-emerald-500/15 text-emerald-800 border-emerald-500/30',
  amber: 'bg-amber-500/15 text-amber-800 border-amber-500/30',
  red: 'bg-red-500/15 text-red-800 border-red-500/30',
}

const STATUS_DOT: Record<'green' | 'amber' | 'red', string> = {
  green: 'bg-emerald-600',
  amber: 'bg-amber-600',
  red: 'bg-red-600',
}

export function DashboardPage({ onOpenScenario }: DashboardPageProps) {
  const [chartDays, setChartDays] = useState<7 | 14 | 30>(14)

  const dashboardQuery = useQuery({
    queryKey: ['dashboard', 14],
    queryFn: () => api.getDashboard(14),
  })

  const forecastQuery = useQuery({
    queryKey: ['forecast', chartDays],
    queryFn: () => api.getForecast(chartDays),
  })

  if (dashboardQuery.isLoading) {
    return (
      <div className="space-y-6">
        <div className="glass-panel rounded-3xl p-8 h-40 animate-pulse" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map((n) => (
            <div key={n} className="glass-panel rounded-2xl p-5 h-28 animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <div className="glass-panel rounded-2xl p-6 border-red-200 text-red-800">
        <h2 className="font-semibold">Unable to load dashboard</h2>
        <p className="text-sm mt-1">{dashboardQuery.error?.message ?? 'Unknown error'}</p>
      </div>
    )
  }

  const d = dashboardQuery.data
  const fc = forecastQuery.data
  const hasGap = Number(d.estimated_cash_gap_vs_reserve) > 0
  const unlockableTotal = Number(d.slow_stock_value_flagged) + Number(d.overdue_receivables)

  const chartData =
    fc?.daily.map((day) => ({
      date: day.date.slice(5),
      closingCash: Number(day.closing_cash),
      confirmedOutflows: -Number(day.confirmed_outflows),
      expectedInflows: Number(day.expected_inflows),
      estimatedNet: Number(day.estimated_inflows) - Number(day.estimated_outflows),
    })) ?? []

  return (
    <div className="space-y-6 cp-enter">
      {/* Cash-Gap Command Banner */}
      <section
        className={`rounded-3xl p-6 sm:p-7 ${
          hasGap ? 'glass-slate text-white' : 'glass-panel text-slate-900'
        }`}
      >
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
          <div className="space-y-2 max-w-2xl">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                  hasGap
                    ? 'bg-red-500/20 text-red-200 border border-red-400/30'
                    : 'bg-emerald-500/15 text-emerald-800 border border-emerald-500/30'
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${hasGap ? 'bg-red-400' : 'bg-emerald-600'}`}
                />
                {hasGap ? 'Projected Cash Gap Alert (14-day radar)' : 'Liquidity Healthy'}
              </span>
              {d.incomplete_data && (
                <span className="rounded-full bg-amber-500/20 text-amber-200 border border-amber-400/30 px-3 py-1 text-xs font-medium">
                  Incomplete data: set opening cash
                </span>
              )}
            </div>

            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
              {hasGap
                ? `Estimated cash gap of ${formatMoney(d.estimated_cash_gap_vs_reserve, d.currency)} below reserve by ${d.gap_date}`
                : `Cash stays above your ${formatMoney(d.min_cash_reserve, d.currency)} reserve over the next 14 days`}
            </h1>
            <p className={`text-sm ${hasGap ? 'text-slate-300' : 'text-slate-600'}`}>
              {hasGap
                ? `Peak deficit below zero: ${formatMoney(d.estimated_cash_gap_vs_zero, d.currency)}. You have ${formatMoney(unlockableTotal, d.currency)} in unlockable internal capital (${formatMoney(d.slow_stock_value_flagged, d.currency)} slow stock + ${formatMoney(d.overdue_receivables, d.currency)} overdue dues) to tap before considering borrowing.`
                : `Current cash on hand is ${formatMoney(d.cash_on_hand, d.currency)}. Keep monitoring payables and slow-moving stock.`}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 shrink-0">
            <div
              className={`rounded-2xl p-4 ${
                hasGap ? 'bg-white/[0.07] border border-white/10' : 'glass-panel-soft'
              }`}
            >
              <p className={`text-xs ${hasGap ? 'text-slate-300' : 'text-slate-500'}`}>
                Unlockable slow stock
              </p>
              <p className="mt-1 text-lg font-semibold tabular-nums">
                {formatMoney(d.slow_stock_value_flagged, d.currency)}
              </p>
              <p className={`text-[11px] ${hasGap ? 'text-teal-300' : 'text-[#0d7480]'}`}>
                {Number(d.slow_stock_pct_of_inventory).toFixed(1)}% of inventory
              </p>
            </div>
            <div
              className={`rounded-2xl p-4 ${
                hasGap ? 'bg-white/[0.07] border border-white/10' : 'glass-panel-soft'
              }`}
            >
              <p className={`text-xs ${hasGap ? 'text-slate-300' : 'text-slate-500'}`}>
                Overdue dues
              </p>
              <p className="mt-1 text-lg font-semibold tabular-nums">
                {formatMoney(d.overdue_receivables, d.currency)}
              </p>
              <p className={`text-[11px] ${hasGap ? 'text-amber-300' : 'text-amber-700'}`}>
                Collect before borrowing
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 5 KPI Cards */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="glass-panel cp-card-lift rounded-2xl p-5">
          <p className="text-xs font-medium text-slate-500">Cash on hand (Now)</p>
          <p className="mt-2 text-xl font-semibold text-[#0d7480] tabular-nums">
            {formatMoney(d.cash_on_hand, d.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Reserve: {formatMoney(d.min_cash_reserve, d.currency)}
          </p>
        </div>

        <div className="glass-panel cp-card-lift rounded-2xl p-5">
          <p className="text-xs font-medium text-slate-500">Estimated cash gap (14d)</p>
          <p
            className={`mt-2 text-xl font-semibold tabular-nums ${
              hasGap ? 'text-red-700' : 'text-emerald-700'
            }`}
          >
            {formatMoney(d.estimated_cash_gap_vs_reserve, d.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {d.gap_date ? `Lowest on ${d.gap_date}` : 'No reserve breach'}
          </p>
        </div>

        <div className="glass-panel cp-card-lift rounded-2xl p-5">
          <p className="text-xs font-medium text-slate-500">Slow-stock flagged</p>
          <p className="mt-2 text-xl font-semibold text-amber-700 tabular-nums">
            {formatMoney(d.slow_stock_value_flagged, d.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Of {formatMoney(d.total_stock_value, d.currency)} stock
          </p>
        </div>

        <div className="glass-panel cp-card-lift rounded-2xl p-5">
          <p className="text-xs font-medium text-slate-500">Customers owe</p>
          <p className="mt-2 text-xl font-semibold text-emerald-700 tabular-nums">
            {formatMoney(d.customers_owe, d.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {formatMoney(d.overdue_receivables, d.currency)} overdue
          </p>
        </div>

        <div className="glass-panel cp-card-lift rounded-2xl p-5">
          <p className="text-xs font-medium text-slate-500">We owe suppliers</p>
          <p className="mt-2 text-xl font-semibold text-slate-900 tabular-nums">
            {formatMoney(d.we_owe_suppliers, d.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">Open payables</p>
        </div>
      </section>

      {/* Forecast Chart + Gap Causes */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 glass-panel rounded-3xl p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Cash-Flow Radar</h2>
              <p className="text-xs text-slate-500">
                Closing cash projection ({d.currency}) · Actual/reserve vs. confirmed, expected &amp;
                estimated flows
              </p>
            </div>
            <div className="flex items-center gap-1 rounded-xl bg-slate-900/[0.05] p-1">
              {([7, 14, 30] as const).map((horizon) => (
                <button
                  key={horizon}
                  type="button"
                  onClick={() => setChartDays(horizon)}
                  className={`cp-btn px-3 py-1.5 rounded-lg text-xs font-medium ${
                    chartDays === horizon
                      ? 'bg-[#13252f] text-white'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {horizon}d
                </button>
              ))}
            </div>
          </div>

          {chartDays === 7 && hasGap && (
            <p className="mt-3 text-xs text-amber-800 bg-amber-50/90 border border-amber-200 rounded-xl px-3 py-2">
              Note: the 7-day view stops before the {d.gap_date} reserve breach shown on the 14-day
              radar.
            </p>
          )}

          <div className="mt-4 h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(19, 37, 47, 0.08)" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#526773' }} />
                <YAxis tick={{ fontSize: 11, fill: '#526773' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.92)',
                    backdropFilter: 'blur(12px)',
                    borderRadius: '14px',
                    border: '1px solid rgba(19, 37, 47, 0.1)',
                    fontSize: '12px',
                  }}
                  formatter={(value, name) => [
                    formatMoney(String(value ?? 0), d.currency),
                    String(name ?? ''),
                  ]}
                />
                <ReferenceLine
                  y={Number(d.min_cash_reserve)}
                  stroke="#e11d48"
                  strokeDasharray="5 5"
                  label={{
                    value: 'Min Reserve',
                    position: 'insideTopRight',
                    fill: '#e11d48',
                    fontSize: 11,
                  }}
                />
                <ReferenceLine y={0} stroke="rgba(19, 37, 47, 0.25)" />
                <Bar
                  dataKey="confirmedOutflows"
                  name="Confirmed Outflows"
                  fill="#dc2626"
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="expectedInflows"
                  name="Expected Inflows"
                  fill="#059669"
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="estimatedNet"
                  name="Estimated Daily Net"
                  fill="#d97706"
                  radius={[4, 4, 0, 0]}
                />
                <Line
                  type="monotone"
                  dataKey="closingCash"
                  name="Closing Cash"
                  stroke="#0d7480"
                  strokeWidth={2.5}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {fc && (
            <p className="mt-3 text-[11px] text-slate-500">
              {fc.limited_data ? 'Limited data (<14 days history) · ' : ''}
              {fc.assumptions_note}
            </p>
          )}
        </div>

        {/* Causes & Unlockable Capital */}
        <div className="lg:col-span-4 glass-panel rounded-3xl p-6 flex flex-col justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Gap Causes &amp; Mitigations</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Outflows and uncollected dues driving liquidity pressure
            </p>

            <div className="mt-4 space-y-2.5">
              {fc?.causes.length ? (
                fc.causes.map((cause, idx) => (
                  <div
                    key={`${cause.label}-${idx}`}
                    className="glass-panel-soft rounded-2xl p-3.5 flex items-start justify-between gap-3"
                  >
                    <div>
                      <span
                        className={`inline-block text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md ${
                          cause.kind === 'outflow'
                            ? 'bg-red-500/12 text-red-700'
                            : 'bg-amber-500/12 text-amber-800'
                        }`}
                      >
                        {cause.kind === 'outflow' ? 'Outflow' : 'Overdue due'}
                      </span>
                      <p className="mt-1 text-sm font-medium text-slate-900">{cause.label}</p>
                      {cause.due_on && (
                        <p className="text-xs text-slate-500">Due: {cause.due_on}</p>
                      )}
                    </div>
                    <span className="text-sm font-semibold tabular-nums text-slate-900 shrink-0">
                      {formatMoney(cause.amount, d.currency)}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No upcoming outflows or overdue dues.</p>
              )}
            </div>
          </div>

          <div className="mt-5 rounded-2xl bg-teal-900/[0.06] border border-teal-900/15 p-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-[#0d7480]">
              Unlockable Capital (Mitigation)
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">
              {formatMoney(d.slow_stock_value_flagged, d.currency)}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              Tied up in slow-moving stock — shown separately as capital you can free before taking
              a loan.
            </p>
          </div>
        </div>
      </section>

      {/* Transparent Financial-Readiness Profile */}
      <section className="glass-panel rounded-3xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-lg font-semibold text-slate-900">
                Transparent Financial-Readiness Profile
              </h2>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border uppercase ${
                  STATUS_BADGE[d.readiness_summary.overall_status]
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    STATUS_DOT[d.readiness_summary.overall_status]
                  }`}
                />
                {d.readiness_summary.overall_status}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">{d.readiness_summary.disclaimer}</p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {d.readiness_summary.dimensions.map((dim) => (
            <article
              key={dim.key}
              className="glass-panel-soft cp-card-lift rounded-2xl p-4 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-900">{dim.label}</h3>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border uppercase ${
                      STATUS_BADGE[dim.status]
                    }`}
                  >
                    {dim.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-700 leading-relaxed">{dim.summary}</p>
                <dl className="mt-3 space-y-1 border-t border-slate-900/8 pt-2.5">
                  {Object.entries(dim.evidence).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-[11px] gap-2">
                      <dt className="text-slate-500 truncate">{k.replaceAll('_', ' ')}</dt>
                      <dd className="font-medium text-slate-800 tabular-nums">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <p className="mt-3 text-[11px] font-medium text-[#0d7480] border-t border-slate-900/8 pt-2">
                Next: {dim.improvement_action}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* Internal-Capital-First Recommendations */}
      <section className="glass-panel rounded-3xl p-6">
        <h2 className="text-lg font-semibold text-slate-900">
          Recommended Actions (Internal Capital First)
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Rule-based actions prioritized to close cash gaps using existing dues, stock, and timing
        </p>

        {d.recommendations.length === 0 ? (
          <div className="mt-4 rounded-2xl glass-panel-soft p-5 text-sm text-emerald-800">
            No urgent cash-gap action needed — projected cash stays above your reserve across the
            next 14 days.
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            {d.recommendations.map((rec) => (
              <article
                key={rec.id}
                className="glass-panel-soft cp-card-lift rounded-2xl p-4 flex flex-col justify-between"
              >
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">{rec.title}</h3>
                  <p className="mt-2 text-xs text-slate-700">{rec.issue}</p>
                  <p className="mt-1.5 text-xs text-slate-500">{rec.evidence}</p>
                  <p className="mt-2 text-xs font-medium text-slate-800">{rec.suggested_action}</p>
                </div>
                <div className="mt-3 pt-2.5 border-t border-slate-900/8 space-y-2">
                  <div>
                    <p className="text-xs font-semibold text-[#0d7480]">{rec.estimated_impact}</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">Limit: {rec.limitations}</p>
                  </div>
                  {rec.suggested_scenario && onOpenScenario && (
                    <button
                      type="button"
                      onClick={() => onOpenScenario(rec.suggested_scenario!)}
                      className="cp-btn w-full py-2 px-3 rounded-xl bg-[#0d7480]/10 text-[#0d7480] text-xs font-semibold hover:bg-[#0d7480] hover:text-white"
                    >
                      Test in Scenario Lab →
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
