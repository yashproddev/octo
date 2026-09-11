import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ReconciliationRun, ResultRow, ResultStatus } from '../types'
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  StatCard,
  StatusPill,
  Td,
  Th,
  compactMoney,
  money,
  num,
} from '../components/ui'

const TILES: { status: ResultStatus; label: string; tone: 'good' | 'info' | 'warn' | 'bad' | 'default' }[] = [
  { status: 'AUTO_CLOSED', label: 'Auto-closed', tone: 'good' },
  { status: 'REVIEW', label: 'Review', tone: 'info' },
  { status: 'MISMATCH', label: 'Mismatch', tone: 'warn' },
  { status: 'DUPLICATE', label: 'Duplicate', tone: 'bad' },
  { status: 'INCOMPLETE', label: 'Incomplete', tone: 'default' },
]

// Lines already closed have nothing left to decide; offering bulk actions on
// them would produce audit noise rather than progress.
const OPEN_STATUSES = new Set<ResultStatus>(['MISMATCH', 'DUPLICATE', 'INCOMPLETE', 'REVIEW'])

type SortKey = 'row_number' | 'exposure' | 'po_number' | 'vendor'

export default function Results() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<ReconciliationRun | null>(null)
  const [rows, setRows] = useState<ResultRow[] | null>(null)
  const [filter, setFilter] = useState<ResultStatus | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'row_number', desc: false })
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    api.get<{ run: ReconciliationRun }>(`/reconciliation/runs/${runId}`)
      .then((d) => setRun(d.run))
      .catch((e) => setError(String(e)))
  }, [runId, nonce])

  useEffect(() => {
    const params = new URLSearchParams()
    if (filter) params.set('status', filter)
    if (query.trim()) params.set('q', query.trim())
    const qs = params.toString()
    setRows(null)
    setSelected(new Set())
    api.get<{ results: ResultRow[] }>(`/reconciliation/runs/${runId}/results${qs ? `?${qs}` : ''}`)
      .then((d) => setRows(d.results))
      .catch((e) => setError(String(e)))
  }, [runId, filter, query, nonce])

  const sorted = useMemo(() => {
    if (!rows) return null
    const copy = [...rows]
    copy.sort((a, b) => {
      const dir = sort.desc ? -1 : 1
      if (sort.key === 'exposure') {
        return (Number(a.exposure ?? 0) - Number(b.exposure ?? 0)) * dir
      }
      if (sort.key === 'row_number') return (a.row_number - b.row_number) * dir
      return String(a[sort.key] ?? '').localeCompare(String(b[sort.key] ?? '')) * dir
    })
    return copy
  }, [rows, sort])

  const selectable = useMemo(
    () => (sorted ?? []).filter((r) => OPEN_STATUSES.has(r.current_status)),
    [sorted],
  )

  if (error) return <ErrorNote title="Could not load results" body={error} />
  if (!run) return <Loading />

  const counts = run.status_counts ?? {}
  const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)
  const openCount = TILES.filter((t) => OPEN_STATUSES.has(t.status)).reduce(
    (a, t) => a + (counts[t.status] ?? 0),
    0,
  )
  const cleared = total - openCount

  async function bulk(action: string) {
    setBusy(true)
    setError(null)
    try {
      await api.post('/decisions/bulk', {
        result_ids: [...selected],
        action,
        reason: reason || undefined,
      })
      setReason('')
      setNonce((n) => n + 1)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key === 'exposure' }))
  }

  const exportUrl = `/api/v1/reconciliation/runs/${runId}/export.csv${filter ? `?status=${filter}` : ''}`

  return (
    <div>
      <PageHeader
        title="Reconciliation Results"
        subtitle={`${total} lines checked under rules ${run.rule_version}. Clean matches close automatically; everything else needs a person.`}
        actions={
          <a href={exportUrl} download>
            <Button variant="secondary">Export CSV</Button>
          </a>
        }
      />

      {/* Money first: a count of exceptions is an operational metric, the amount
          at risk is the one anybody outside this screen actually asks about. */}
      <div className="mb-4 flex flex-wrap items-end gap-x-8 gap-y-3 rounded-lg border border-gray-200 bg-white px-5 py-4 shadow-sm">
        <div>
          <div className="text-xs text-gray-500">Value at risk</div>
          <div className="mt-0.5 text-3xl font-semibold tracking-tight text-amber-700">
            ₹{money(run.total_exposure)}
          </div>
          <div className="mt-0.5 text-xs text-gray-400">
            if every exception were paid exactly as billed
          </div>
        </div>
        <div className="flex-1">
          <div className="flex items-baseline justify-between text-xs text-gray-500">
            <span>Review progress</span>
            <span className="font-medium text-gray-700">
              {cleared} of {total} cleared
            </span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-teal-600 transition-all"
              style={{ width: `${total ? (cleared / total) * 100 : 0}%` }}
            />
          </div>
          <div className="mt-1 text-xs text-gray-400">{openCount} still open</div>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="All lines" value={total} onClick={() => setFilter(null)} active={filter === null} />
        {TILES.map((t) => (
          <StatCard
            key={t.status}
            label={t.label}
            value={counts[t.status] ?? 0}
            tone={t.tone}
            onClick={() => setFilter(filter === t.status ? null : t.status)}
            active={filter === t.status}
          />
        ))}
      </div>

      {selected.size > 0 && (
        <div className="sticky top-3 z-20 mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-teal-600 bg-teal-900 px-4 py-2.5 shadow-lg">
          <span className="text-sm font-medium text-white">{selected.size} selected</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (required to reject)"
            className="min-w-56 flex-1 rounded-md border border-teal-700 bg-teal-950/50 px-2.5 py-1.5 text-sm text-white placeholder:text-teal-300/60 focus:border-teal-400 focus:outline-none"
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => void bulk('APPROVE')}>
              Approve all
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void bulk('RESOLVE')}>
              Resolve all
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy || !reason.trim()}
              onClick={() => void bulk('REJECT')}
            >
              Reject all
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        </div>
      )}

      <Card
        title={filter ? `Filtered: ${filter}` : 'All lines'}
        description="Select open lines to act on several at once, or click one to see every check."
        actions={
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search PO, vendor, item…"
            className="w-56 rounded-md border border-gray-300 px-2.5 py-1.5 text-sm placeholder:text-gray-400 focus:border-teal-600 focus:outline-none"
          />
        }
        padded={false}
      >
        {sorted === null ? (
          <Loading />
        ) : sorted.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing here" body="No lines match the current filter." />
          </div>
        ) : (
          <div className="max-h-[70vh] overflow-auto">
            <table className="w-full">
              <thead className="sticky top-0 z-10 bg-white shadow-[0_1px_0_var(--color-gray-200)]">
                <tr>
                  <Th>
                    <input
                      type="checkbox"
                      aria-label="Select all open lines"
                      className="size-3.5 rounded border-gray-300 accent-teal-700"
                      checked={selectable.length > 0 && selected.size === selectable.length}
                      onChange={(e) =>
                        setSelected(e.target.checked ? new Set(selectable.map((r) => r.id)) : new Set())
                      }
                    />
                  </Th>
                  <SortTh label="Row" active={sort} k="row_number" onClick={toggleSort} />
                  <SortTh label="PO" active={sort} k="po_number" onClick={toggleSort} />
                  <SortTh label="Vendor" active={sort} k="vendor" onClick={toggleSort} />
                  <Th>Item</Th>
                  <Th align="right">PO qty</Th>
                  <Th align="right">GRN qty</Th>
                  <Th align="right">Inv qty</Th>
                  <Th align="right">PO price</Th>
                  <Th align="right">Inv price</Th>
                  <SortTh label="At risk" active={sort} k="exposure" onClick={toggleSort} align="right" />
                  <Th>Status</Th>
                  <Th>Failed check</Th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => {
                  const open = OPEN_STATUSES.has(r.current_status)
                  const risk = Number(r.exposure ?? 0)
                  return (
                    <tr
                      key={r.id}
                      className={selected.has(r.id) ? 'bg-teal-50/60' : 'hover:bg-gray-50'}
                    >
                      <Td>
                        <input
                          type="checkbox"
                          aria-label={`Select row ${r.row_number}`}
                          disabled={!open}
                          checked={selected.has(r.id)}
                          onChange={(e) =>
                            setSelected((s) => {
                              const next = new Set(s)
                              if (e.target.checked) next.add(r.id)
                              else next.delete(r.id)
                              return next
                            })
                          }
                          className="size-3.5 rounded border-gray-300 accent-teal-700 disabled:opacity-30"
                        />
                      </Td>
                      <Td muted>{r.row_number}</Td>
                      <Td>
                        <Link
                          to={`/reconciliation/${runId}/results/${r.id}`}
                          className="font-medium text-teal-700 hover:underline"
                        >
                          {r.po_number || '—'}
                        </Link>
                      </Td>
                      <Td muted>{r.vendor || '—'}</Td>
                      <Td>{r.item || '—'}</Td>
                      <Td align="right">{num(r.po_quantity)}</Td>
                      <Td align="right">{num(r.grn_quantity)}</Td>
                      <Td align="right">{num(r.invoice_quantity)}</Td>
                      <Td align="right">{num(r.po_unit_price)}</Td>
                      <Td align="right">{num(r.invoice_unit_price)}</Td>
                      <Td align="right">
                        {r.exposure === null ? (
                          <span className="text-gray-300" title="Too incomplete to value">
                            —
                          </span>
                        ) : risk > 0 ? (
                          <span className="font-medium text-amber-700">₹{compactMoney(r.exposure)}</span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </Td>
                      <Td>
                        <StatusPill status={r.current_status} />
                      </Td>
                      <Td>
                        {r.failed_checks.length === 0 ? (
                          <span className="text-gray-300">—</span>
                        ) : (
                          <span className="flex flex-wrap gap-1">
                            {r.failed_checks.map((c) => (
                              <span
                                key={c}
                                className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600"
                              >
                                {c}
                              </span>
                            ))}
                          </span>
                        )}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function SortTh({
  label,
  k,
  active,
  onClick,
  align = 'left',
}: {
  label: string
  k: SortKey
  active: { key: SortKey; desc: boolean }
  onClick: (k: SortKey) => void
  align?: 'left' | 'right'
}) {
  const on = active.key === k
  return (
    <th
      className={`whitespace-nowrap border-b border-gray-200 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide ${
        align === 'right' ? 'text-right' : 'text-left'
      } ${on ? 'text-teal-700' : 'text-gray-500'}`}
    >
      <button onClick={() => onClick(k)} className="inline-flex items-center gap-1 hover:text-teal-700">
        {label}
        <span className={on ? 'opacity-100' : 'opacity-0'}>{active.desc ? '▾' : '▴'}</span>
      </button>
    </th>
  )
}
