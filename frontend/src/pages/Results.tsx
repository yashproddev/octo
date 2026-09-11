import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ReconciliationRun, ResultRow, ResultStatus } from '../types'
import {
  Card,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  StatCard,
  StatusPill,
  Td,
  Th,
  num,
} from '../components/ui'

const TILES: { status: ResultStatus; label: string; tone: 'good' | 'info' | 'warn' | 'bad' | 'default' }[] = [
  { status: 'AUTO_CLOSED', label: 'Auto-closed', tone: 'good' },
  { status: 'REVIEW', label: 'Review', tone: 'info' },
  { status: 'MISMATCH', label: 'Mismatch', tone: 'warn' },
  { status: 'DUPLICATE', label: 'Duplicate', tone: 'bad' },
  { status: 'INCOMPLETE', label: 'Incomplete', tone: 'default' },
]

export default function Results() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<ReconciliationRun | null>(null)
  const [rows, setRows] = useState<ResultRow[] | null>(null)
  const [filter, setFilter] = useState<ResultStatus | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<{ run: ReconciliationRun }>(`/reconciliation/runs/${runId}`)
      .then((d) => setRun(d.run))
      .catch((e) => setError(String(e)))
  }, [runId])

  useEffect(() => {
    const params = new URLSearchParams()
    if (filter) params.set('status', filter)
    if (query.trim()) params.set('q', query.trim())
    const qs = params.toString()
    setRows(null)
    api.get<{ results: ResultRow[] }>(`/reconciliation/runs/${runId}/results${qs ? `?${qs}` : ''}`)
      .then((d) => setRows(d.results))
      .catch((e) => setError(String(e)))
  }, [runId, filter, query])

  if (error) return <ErrorNote title="Could not load results" body={error} />
  if (!run) return <Loading />

  const counts = run.status_counts ?? {}
  const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)

  return (
    <div>
      <PageHeader
        title="Reconciliation Results"
        subtitle={`${total} lines checked under rules ${run.rule_version}. Clean matches are closed automatically; everything else needs a person.`}
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard
          label="All lines"
          value={total}
          onClick={() => setFilter(null)}
          active={filter === null}
        />
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

      <Card
        title={filter ? `Filtered: ${filter}` : 'All lines'}
        description="Click any line to see every check and record a decision."
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
        {rows === null ? (
          <Loading />
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing here" body="No lines match the current filter." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <Th>Row</Th>
                  <Th>PO</Th>
                  <Th>Vendor</Th>
                  <Th>Item</Th>
                  <Th align="right">PO qty</Th>
                  <Th align="right">GRN qty</Th>
                  <Th align="right">Inv qty</Th>
                  <Th align="right">PO price</Th>
                  <Th align="right">Inv price</Th>
                  <Th>Status</Th>
                  <Th>Failed check</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <Td muted>
                      <Link to={`/reconciliation/${runId}/results/${r.id}`} className="hover:underline">
                        {r.row_number}
                      </Link>
                    </Td>
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
