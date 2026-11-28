import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatMoney } from '../api'
import type { AdvisorAskResponse, BusinessOut } from '../types'

interface AdvisorPageProps {
  business: BusinessOut
}

const DEMO_PROMPTS = [
  'Why could I run out of cash next week?',
  'Can I afford a 15,000 purchase?',
  'How much cash is tied up in slow stock and overdue dues?',
  'Should I take a loan?',
]

interface ExchangeItem {
  id: string
  question: string
  response: AdvisorAskResponse
}

export function AdvisorPage({ business }: AdvisorPageProps) {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState('')
  const [exchanges, setExchanges] = useState<ExchangeItem[]>([])
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({})

  const historyQuery = useQuery({
    queryKey: ['advisor-history'],
    queryFn: api.getAdvisorHistory,
  })

  const askMutation = useMutation({
    mutationFn: (q: string) => api.askAdvisor(q),
    onSuccess: (response, submittedQuestion) => {
      setExchanges((prev) => [
        { id: response.log_id, question: submittedQuestion, response },
        ...prev,
      ])
      setQuestion('')
      void queryClient.invalidateQueries({ queryKey: ['advisor-history'] })
    },
  })

  const submitQuestion = (rawQ: string) => {
    const trimmed = rawQ.trim()
    if (!trimmed || askMutation.isPending) return
    askMutation.mutate(trimmed)
  }

  return (
    <div className="space-y-6 cp-enter">
      <section className="glass-panel rounded-3xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">AI Advisor</h1>
            <p className="text-sm text-slate-500">
              Read-only advisor grounded in backend tools. Each question stands alone against your
              live records.
            </p>
          </div>
          <span className="text-xs px-3 py-1 rounded-full glass-panel-soft text-[#0d7480] font-medium">
            Read-only · Tool-grounded
          </span>
        </div>

        {/* Quick-ask demo pills */}
        <div className="mt-4 flex flex-wrap gap-2">
          {DEMO_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              disabled={askMutation.isPending}
              onClick={() => submitQuestion(prompt)}
              className="cp-btn px-3 py-1.5 rounded-xl glass-panel-soft text-xs font-medium text-slate-700 hover:text-[#0d7480] disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>

        <form
          className="mt-4 flex flex-col sm:flex-row gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            submitQuestion(question)
          }}
        >
          <input
            type="text"
            maxLength={500}
            required
            disabled={askMutation.isPending}
            placeholder="Ask about cash gaps, affordability, slow stock, or readiness (max 500 chars)..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="cp-input flex-1 rounded-2xl px-4 py-3 text-sm disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={askMutation.isPending || !question.trim()}
            className="cp-btn min-h-[46px] px-6 rounded-2xl bg-[#0d7480] text-white text-sm font-medium hover:bg-[#0a5c66] disabled:opacity-50"
          >
            {askMutation.isPending ? 'Analyzing records...' : 'Ask advisor'}
          </button>
        </form>

        {askMutation.isError && (
          <div className="mt-3 rounded-xl bg-red-50 border border-red-200 p-3 text-xs text-red-700">
            {askMutation.error.message}
          </div>
        )}
      </section>

      {/* Loading skeleton (5-15s LLM / tool latency) */}
      {askMutation.isPending && (
        <section className="glass-panel rounded-3xl p-6 space-y-3 animate-pulse">
          <div className="h-4 w-48 bg-slate-900/10 rounded" />
          <div className="h-3 w-full bg-slate-900/8 rounded" />
          <div className="h-3 w-4/5 bg-slate-900/8 rounded" />
        </section>
      )}

      {/* Live Session Answers */}
      <section className="space-y-4">
        {exchanges.map((item) => {
          const r = item.response
          const open = Boolean(expandedTools[item.id])
          return (
            <article key={item.id} className="glass-panel cp-enter rounded-3xl p-6 space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
                    Question
                  </p>
                  <h2 className="text-base font-semibold text-slate-900">{item.question}</h2>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {r.fallback_used && (
                    <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-800 border border-amber-500/30">
                      Generated directly from your data
                    </span>
                  )}
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium border ${
                      r.number_check_passed
                        ? 'bg-emerald-500/12 text-emerald-800 border-emerald-500/25'
                        : 'bg-slate-900/6 text-slate-600 border-slate-900/10'
                    }`}
                  >
                    {r.number_check_passed ? 'Numbers verified' : 'Direct tool summary'}
                  </span>
                </div>
              </div>

              <p className="text-sm text-slate-800 leading-relaxed">{r.summary}</p>

              {r.figures.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {r.figures.map((fig) => (
                    <div
                      key={`${fig.tool}-${fig.field}`}
                      className="glass-panel-soft rounded-2xl p-3.5"
                    >
                      <p className="text-xs text-slate-500">{fig.label}</p>
                      <p className="mt-1 text-base font-semibold tabular-nums text-[#0d7480]">
                        {fig.unit === '%' || fig.unit === 'days'
                          ? `${Number(fig.value).toLocaleString()} ${fig.unit}`
                          : formatMoney(fig.value, business.currency)}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {(r.assumptions.length > 0 || r.limitations.length > 0) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  {r.assumptions.length > 0 && (
                    <div className="rounded-2xl bg-slate-900/[0.03] p-3">
                      <p className="font-semibold text-slate-700">Assumptions</p>
                      <ul className="mt-1 space-y-1 text-slate-600 list-disc list-inside">
                        {r.assumptions.map((a, idx) => (
                          <li key={idx}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {r.limitations.length > 0 && (
                    <div className="rounded-2xl bg-slate-900/[0.03] p-3">
                      <p className="font-semibold text-slate-700">Limitations</p>
                      <ul className="mt-1 space-y-1 text-slate-600 list-disc list-inside">
                        {r.limitations.map((l, idx) => (
                          <li key={idx}>{l}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              <div className="pt-2 border-t border-slate-900/10">
                <button
                  type="button"
                  onClick={() =>
                    setExpandedTools((prev) => ({ ...prev, [item.id]: !prev[item.id] }))
                  }
                  className="cp-btn text-xs font-medium text-[#0d7480] hover:underline"
                >
                  {open
                    ? 'Hide tools used & evidence'
                    : `Show tools used & evidence (${r.tools_called.length})`}
                </button>

                {open && (
                  <div className="mt-3 space-y-2 text-xs">
                    {r.evidence.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {r.evidence.map((ev) => (
                          <span
                            key={ev}
                            className="px-2 py-0.5 rounded-md bg-teal-900/10 text-[#0d7480] font-mono text-[11px]"
                          >
                            {ev}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="space-y-1">
                      {r.tools_called.map((tc, i) => (
                        <div
                          key={`${tc.tool}-${i}`}
                          className="glass-panel-soft rounded-xl px-3 py-2 flex flex-wrap justify-between gap-2"
                        >
                          <span className="font-mono font-medium text-slate-800">{tc.tool}</span>
                          <span className="text-slate-500 font-mono truncate max-w-md">
                            {JSON.stringify(tc.args)} → {tc.summary}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </article>
          )
        })}
      </section>

      {/* Saved Audit History */}
      {historyQuery.data && historyQuery.data.length > 0 && (
        <section className="glass-panel rounded-3xl p-6">
          <h2 className="text-base font-semibold text-slate-900">Recent Advisor Audit Log</h2>
          <div className="mt-3 divide-y divide-slate-900/8">
            {historyQuery.data.slice(0, 6).map((log) => (
              <div key={log.id} className="py-3 text-xs space-y-1">
                <p className="font-medium text-slate-900">{log.question}</p>
                <p className="text-slate-600">{log.answer}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
