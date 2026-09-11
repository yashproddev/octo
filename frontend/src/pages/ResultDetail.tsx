import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Finding, ResultDetail as Detail, ResultRow } from '../types'
import {
  Button,
  Card,
  ErrorNote,
  Loading,
  PageHeader,
  StatusPill,
  Td,
  Th,
  formatDateTime,
  money,
  num,
} from '../components/ui'

const ACTIONS = [
  { action: 'APPROVE', label: 'Approve', variant: 'primary' as const, needsReason: false },
  { action: 'RESOLVE', label: 'Resolve', variant: 'secondary' as const, needsReason: false },
  { action: 'OVERRIDE', label: 'Override', variant: 'secondary' as const, needsReason: true },
  { action: 'REJECT', label: 'Reject', variant: 'danger' as const, needsReason: true },
]

export default function ResultDetail() {
  const { runId = '', resultId = '' } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [queue, setQueue] = useState<ResultRow[]>([])

  const load = () =>
    api.get<Detail>(`/reconciliation/results/${resultId}`).then(setDetail).catch((e) => setError(String(e)))

  useEffect(() => {
    void load()
  }, [resultId])

  // The open exceptions, so a reviewer can walk the queue without returning to
  // the list between every decision.
  useEffect(() => {
    if (!runId) return
    api.get<{ results: ResultRow[] }>(`/reconciliation/runs/${runId}/results`)
      .then((d) => setQueue(d.results.filter((r) => r.current_status !== 'AUTO_CLOSED')))
      .catch(() => undefined)
  }, [runId, resultId])

  if (error && !detail) return <ErrorNote title="Could not load this line" body={error} />
  if (!detail) return <Loading />

  const s = detail.snapshot
  const risk = Number(detail.snapshot.exposure ?? 0)
  const position = queue.findIndex((r) => r.id === resultId)
  const prev = position > 0 ? queue[position - 1] : null
  const next = position >= 0 && position < queue.length - 1 ? queue[position + 1] : null

  async function decide(action: string) {
    setBusy(true)
    setError(null)
    try {
      await api.post('/decisions', { result_id: resultId, action, reason: reason || undefined })
      setReason('')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={`${s.po_number || 'No PO'} · ${s.item || 'Unnamed item'}`}
        subtitle={detail.explanation}
        actions={
          <>
            {position >= 0 && queue.length > 0 && (
              <span className="mr-1 text-xs text-gray-500">
                Exception {position + 1} of {queue.length}
              </span>
            )}
            <Link
              to={prev ? `/reconciliation/${runId}/results/${prev.id}` : '#'}
              aria-disabled={!prev}
              className={prev ? '' : 'pointer-events-none opacity-40'}
            >
              <Button variant="secondary" size="sm">
                ← Prev
              </Button>
            </Link>
            <Link
              to={next ? `/reconciliation/${runId}/results/${next.id}` : '#'}
              aria-disabled={!next}
              className={next ? '' : 'pointer-events-none opacity-40'}
            >
              <Button variant="secondary" size="sm">
                Next →
              </Button>
            </Link>
            <Link to={`/reconciliation/${runId}`}>
              <Button variant="secondary">All results</Button>
            </Link>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">System verdict</span>
          <StatusPill status={detail.system_status} />
        </div>
        <span className="text-gray-300">→</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Current</span>
          <StatusPill status={detail.current_status} />
        </div>
        {risk > 0 && (
          <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1">
            <span className="text-xs text-amber-800">At risk</span>
            <span className="text-sm font-semibold text-amber-800">
              ₹{money(detail.snapshot.exposure)}
            </span>
          </div>
        )}
        {detail.rule_version && (
          <span className="ml-auto text-xs text-gray-400">Rules {detail.rule_version}</span>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-4">
          <Card title="Order, receipt, invoice" description="The three documents side by side." padded={false}>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Measure</Th>
                    <Th align="right">Purchase order</Th>
                    <Th align="right">Goods receipt</Th>
                    <Th align="right">Invoice</Th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <Td muted>Quantity</Td>
                    <Td align="right">{num(s.po_quantity)}</Td>
                    <Td align="right">{num(s.grn_quantity)}</Td>
                    <Td align="right">{num(s.invoice_quantity)}</Td>
                  </tr>
                  <tr>
                    <Td muted>Unit price</Td>
                    <Td align="right">{num(s.po_unit_price)}</Td>
                    <Td align="right" muted>—</Td>
                    <Td align="right">{num(s.invoice_unit_price)}</Td>
                  </tr>
                  <tr>
                    <Td muted>Tax</Td>
                    <Td align="right" muted>—</Td>
                    <Td align="right" muted>—</Td>
                    <Td align="right">{num(s.tax)}</Td>
                  </tr>
                  <tr>
                    <Td muted>Reference</Td>
                    <Td align="right">{s.po_number || '—'}</Td>
                    <Td align="right" muted>—</Td>
                    <Td align="right">{s.invoice_number || '—'}</Td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Checks" description="Every rule the engine applied, and what it found." padded={false}>
            <ul className="divide-y divide-gray-100">
              {detail.findings.map((f) => (
                <FindingRow key={f.rule_id} finding={f} />
              ))}
            </ul>
          </Card>

          {detail.source_row && (
            <Card
              title={`Original CSV row ${detail.source_row.row_number}`}
              description="Exactly as it appeared in the uploaded file."
            >
              <div className="overflow-x-auto">
                <table className="w-full">
                  <tbody>
                    {Object.entries(detail.source_row.raw_data).map(([k, v]) => (
                      <tr key={k}>
                        <Td muted>{k}</Td>
                        <Td>{v || <span className="text-gray-400">empty</span>}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <Card title="Record a decision" description="Appended to the audit log — the system verdict is never overwritten.">
            {error && (
              <div className="mb-3">
                <ErrorNote title="Not recorded" body={error} />
              </div>
            )}
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Reason (required for Override and Reject)"
              className="w-full rounded-md border border-gray-300 px-2.5 py-2 text-sm placeholder:text-gray-400 focus:border-teal-600 focus:outline-none"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {ACTIONS.map((a) => (
                <Button
                  key={a.action}
                  variant={a.variant}
                  size="sm"
                  disabled={busy || (a.needsReason && !reason.trim())}
                  onClick={() => void decide(a.action)}
                >
                  {a.label}
                </Button>
              ))}
            </div>
          </Card>

          <Card title="Decision history" description="Append-only." padded={false}>
            {detail.decisions.length === 0 ? (
              <p className="p-5 text-sm text-gray-500">No decisions recorded yet.</p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {detail.decisions.map((d) => (
                  <li key={d.id} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-gray-900">
                        {d.action}
                        {d.is_system && (
                          <span className="ml-1.5 rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase tracking-wide text-gray-500">
                            system
                          </span>
                        )}
                      </span>
                      <span className="text-xs text-gray-400">{formatDateTime(d.decided_at)}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {d.actor} ·{' '}
                      {d.from_status === d.to_status
                        ? `remains ${d.to_status}`
                        : `${d.from_status} → ${d.to_status}`}
                    </p>
                    {d.reason && <p className="mt-1 text-sm text-gray-700">{d.reason}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function FindingRow({ finding }: { finding: Finding }) {
  const tone = finding.skipped
    ? 'bg-gray-300'
    : finding.passed
      ? 'bg-teal-500'
      : finding.severity === 'hard'
        ? 'bg-amber-500'
        : 'bg-blue-500'

  return (
    <li className="flex gap-3 px-5 py-3">
      <span className={`mt-1.5 size-2 shrink-0 rounded-full ${tone}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-gray-900">{finding.label}</span>
          <code className="text-[11px] text-gray-400">{finding.rule_id}</code>
          {finding.skipped && (
            <span className="rounded bg-gray-100 px-1 text-[10px] uppercase tracking-wide text-gray-500">
              not checked
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-gray-600">{finding.explanation}</p>
        {(finding.expected || finding.actual) && !finding.skipped && (
          <p className="mt-1 text-xs text-gray-400">
            expected {finding.expected ?? '—'} · actual {finding.actual ?? '—'}
            {finding.variance && ` · variance ${finding.variance}`}
            {finding.tolerance && ` · tolerance ${finding.tolerance}`}
          </p>
        )}
      </div>
    </li>
  )
}
