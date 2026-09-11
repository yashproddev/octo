import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Overview as OverviewData, ReconciliationRun } from '../types'
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
  formatDateTime,
} from '../components/ui'

export default function Overview() {
  const navigate = useNavigate()
  const [data, setData] = useState<OverviewData | null>(null)
  const [runs, setRuns] = useState<ReconciliationRun[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<OverviewData>('/overview').then(setData).catch((e) => setError(String(e)))
    api.get<{ runs: ReconciliationRun[] }>('/reconciliation/runs')
      .then((d) => setRuns(d.runs))
      .catch(() => undefined)
  }, [])

  if (error) return <ErrorNote title="Could not load the overview" body={error} />
  if (!data) return <Loading />

  const counts = data.latest_run?.status_counts ?? {}
  const hasData = data.totals.reconciliation_runs > 0

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Vendor reconciliation and closure. Upload a dataset, review the exceptions, close them with an audit trail."
        actions={
          <Link to="/upload">
            <Button>Upload dataset</Button>
          </Link>
        }
      />

      {!hasData ? (
        <EmptyState
          title="No reconciliation runs yet"
          body="Upload a CSV of purchase, receipt and invoice lines to see how they reconcile."
          action={
            <Link to="/upload">
              <Button>Upload dataset</Button>
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Auto-closed" value={counts.AUTO_CLOSED ?? 0} tone="good" />
            <StatCard label="Review" value={counts.REVIEW ?? 0} tone="info" />
            <StatCard label="Mismatch" value={counts.MISMATCH ?? 0} tone="warn" />
            <StatCard label="Duplicate" value={counts.DUPLICATE ?? 0} tone="bad" />
            <StatCard label="Incomplete" value={counts.INCOMPLETE ?? 0} />
            <StatCard label="Human decisions" value={data.totals.human_decisions} />
          </div>

          {data.latest_run && (
            <div className="mb-4">
              <Card
                title="Latest reconciliation run"
                description={`Rules ${data.latest_run.rule_version} · completed ${formatDateTime(data.latest_run.completed_at)}`}
                actions={
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => navigate(`/reconciliation/${data.latest_run!.id}`)}
                  >
                    Open results
                  </Button>
                }
              >
                <div className="flex flex-wrap gap-2">
                  {Object.entries(counts).map(([status, n]) => (
                    <span key={status} className="flex items-center gap-1.5">
                      <StatusPill status={status} />
                      <span className="text-sm text-gray-600">{n}</span>
                    </span>
                  ))}
                </div>
              </Card>
            </div>
          )}
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Reconciliation runs" description="Each run is independent." padded={false}>
          {runs.length === 0 ? (
            <p className="p-5 text-sm text-gray-500">None yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Completed</Th>
                    <Th>Rules</Th>
                    <Th align="right">Lines</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {runs.slice(0, 8).map((r) => {
                    const total = Object.values(r.status_counts ?? {}).reduce(
                      (a, b) => a + (b ?? 0),
                      0,
                    )
                    return (
                      <tr key={r.id} className="hover:bg-gray-50">
                        <Td>{formatDateTime(r.completed_at ?? r.started_at)}</Td>
                        <Td muted>{r.rule_version}</Td>
                        <Td align="right">{total}</Td>
                        <Td align="right">
                          <Link
                            to={`/reconciliation/${r.id}`}
                            className="text-sm font-medium text-teal-700 hover:underline"
                          >
                            Open
                          </Link>
                        </Td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Uploads" description="Every file, including rejected ones." padded={false}>
          {data.recent_ingestion_runs.length === 0 ? (
            <p className="p-5 text-sm text-gray-500">None yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>File</Th>
                    <Th>Status</Th>
                    <Th align="right">Rows</Th>
                    <Th align="right">Errors</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_ingestion_runs.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <Td>
                        <Link to={`/runs/${r.id}/mapping`} className="text-teal-700 hover:underline">
                          {r.source_filename}
                        </Link>
                      </Td>
                      <Td muted>{r.status.replace(/_/g, ' ').toLowerCase()}</Td>
                      <Td align="right">{r.row_count}</Td>
                      <Td align="right">
                        {r.error_row_count > 0 ? (
                          <span className="text-amber-700">{r.error_row_count}</span>
                        ) : (
                          <span className="text-gray-400">0</span>
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
    </div>
  )
}
