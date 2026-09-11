import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DecisionLogRow } from '../types'
import {
  Card,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  StatusPill,
  Td,
  Th,
  formatDateTime,
} from '../components/ui'

export default function DecisionLog() {
  const [rows, setRows] = useState<DecisionLogRow[] | null>(null)
  const [includeSystem, setIncludeSystem] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRows(null)
    api.get<{ decisions: DecisionLogRow[] }>(`/decisions?include_system=${includeSystem}`)
      .then((d) => setRows(d.decisions))
      .catch((e) => setError(String(e)))
  }, [includeSystem])

  if (error) return <ErrorNote title="Could not load the decision log" body={error} />

  return (
    <div>
      <PageHeader
        title="Decision Log"
        subtitle="Append-only. Every closure is recorded against the system's original verdict, which is never overwritten."
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={includeSystem}
              onChange={(e) => setIncludeSystem(e.target.checked)}
              className="size-3.5 rounded border-gray-300 accent-teal-700"
            />
            Include automatic closures
          </label>
        }
      />

      <Card padded={false}>
        {rows === null ? (
          <Loading />
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="Nothing decided yet"
              body="Decisions appear here as soon as a line is closed, automatically or by a person."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Actor</Th>
                  <Th>Action</Th>
                  <Th>PO / Item</Th>
                  <Th>System verdict</Th>
                  <Th>Result</Th>
                  <Th>Reason</Th>
                  <Th>Rules</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} className="hover:bg-gray-50">
                    <Td muted>{formatDateTime(d.decided_at)}</Td>
                    <Td>
                      {d.actor}
                      {d.is_system && (
                        <span className="ml-1.5 rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase tracking-wide text-gray-500">
                          auto
                        </span>
                      )}
                    </Td>
                    <Td>{d.action}</Td>
                    <Td>
                      <Link
                        to={`/results/${d.result_id}`}
                        className="text-teal-700 hover:underline"
                      >
                        {d.snapshot?.po_number || '—'}
                      </Link>
                      <span className="ml-1 text-gray-500">{d.snapshot?.item || ''}</span>
                    </Td>
                    <Td>{d.system_status && <StatusPill status={d.system_status} />}</Td>
                    <Td>
                      {d.from_status === d.to_status ? (
                        <span className="text-xs text-gray-500">
                          stays <StatusPill status={d.to_status} />
                        </span>
                      ) : (
                        <StatusPill status={d.to_status} />
                      )}
                    </Td>
                    <Td muted>{d.reason || '—'}</Td>
                    <Td muted>{d.rule_version}</Td>
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
