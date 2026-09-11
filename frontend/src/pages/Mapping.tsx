import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  ColumnMatch,
  ExpectedFormat,
  IngestionRun,
  ReconciliationRun,
  RowError,
} from '../types'
import {
  Button,
  Card,
  ErrorNote,
  Loading,
  PageHeader,
  Td,
  Th,
} from '../components/ui'

interface RunDetail {
  run: IngestionRun
  source_columns: string[]
  expected_format: ExpectedFormat
}

const MATCH_LABEL: Record<string, string> = {
  exact: 'Exact',
  alias: 'Recognised',
  manual: 'Manual',
  unmapped: 'Unmapped',
}

const MATCH_STYLE: Record<string, string> = {
  exact: 'bg-teal-50 text-teal-700 ring-teal-600/20',
  alias: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  manual: 'bg-amber-50 text-amber-800 ring-amber-600/25',
  unmapped: 'bg-gray-100 text-gray-500 ring-gray-400/20',
}

export default function Mapping() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [tol, setTol] = useState({
    qty_tolerance_abs: '0',
    qty_tolerance_pct: '0',
    price_tolerance_pct: '0.5',
    tax_tolerance_abs: '1.00',
    expected_tax_rate: '0.18',
  })

  const load = () =>
    api.get<RunDetail>(`/ingestion/runs/${runId}`).then(setDetail).catch((e) => setError(String(e)))

  useEffect(() => {
    void load()
  }, [runId])

  const allFields = useMemo(() => {
    if (!detail) return []
    return [...detail.expected_format.required, ...detail.expected_format.optional]
  }, [detail])

  if (error) return <ErrorNote title="Could not load this run" body={error} />
  if (!detail) return <Loading />

  const { run, source_columns } = detail
  const mapping = (run.column_mapping ?? {}) as Record<string, ColumnMatch>
  const requiredNames = new Set(detail.expected_format.required.map((f) => f.field))
  const missing = detail.expected_format.required
    .map((f) => f.field)
    .filter((f) => !mapping[f] && !overrides[f])

  async function applyMapping() {
    setBusy(true)
    setError(null)
    try {
      if (Object.keys(overrides).length > 0) {
        await api.put(`/ingestion/runs/${runId}/mapping`, { overrides })
        setOverrides({})
      }
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function reconcileNow() {
    setBusy(true)
    setError(null)
    try {
      if (Object.keys(overrides).length > 0) {
        await api.put(`/ingestion/runs/${runId}/mapping`, { overrides })
      }
      const res = await api.post<{ run: ReconciliationRun }>('/reconciliation/runs', {
        ingestion_run_id: runId,
        tolerances: tol,
      })
      navigate(`/reconciliation/${res.run.id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Validation & Mapping"
        subtitle={`${run.source_filename} — ${run.row_count} rows, ${run.valid_row_count} valid, ${run.error_row_count} with errors.`}
        actions={
          <>
            <Button variant="secondary" onClick={() => void applyMapping()} disabled={busy}>
              Re-check mapping
            </Button>
            <Button onClick={() => void reconcileNow()} disabled={busy || missing.length > 0}>
              {busy ? 'Working…' : 'Normalize & reconcile'}
            </Button>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorNote title="That didn't work" body={error} />
        </div>
      )}

      {missing.length > 0 && (
        <div className="mb-4">
          <ErrorNote
            title="Required fields still need a column"
            body="Pick a source column for each one below before reconciling."
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card title="Column mapping" description="Automatic matches are deterministic. Override any of them." padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <Th>Canonical field</Th>
                  <Th>Source column</Th>
                  <Th>Match</Th>
                </tr>
              </thead>
              <tbody>
                {allFields.map((f) => {
                  const current = overrides[f.field] ?? mapping[f.field]?.source_column ?? ''
                  const match = overrides[f.field]
                    ? 'manual'
                    : (mapping[f.field]?.match ?? 'unmapped')
                  const isRequired = requiredNames.has(f.field)
                  return (
                    <tr key={f.field}>
                      <Td>
                        <code className="text-xs text-gray-800">{f.field}</code>
                        {isRequired && <span className="ml-1 text-red-600">*</span>}
                      </Td>
                      <Td>
                        <select
                          value={current}
                          onChange={(e) =>
                            setOverrides((o) => ({ ...o, [f.field]: e.target.value }))
                          }
                          className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-800 focus:border-teal-600 focus:outline-none"
                        >
                          <option value="">— not mapped —</option>
                          {source_columns.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </Td>
                      <Td>
                        <span
                          className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${MATCH_STYLE[match]}`}
                        >
                          {MATCH_LABEL[match]}
                        </span>
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Unmapped columns" description="Present in the file, not used.">
            {run.unmapped_columns.length === 0 ? (
              <p className="text-sm text-gray-500">Every column was recognised.</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {run.unmapped_columns.map((c) => (
                  <li key={c} className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {c}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card
            title="Tolerances"
            description="Frozen onto the run, so results stay explainable later."
          >
            <div className="grid grid-cols-2 gap-3">
              <TolField
                label="Quantity (units)"
                value={tol.qty_tolerance_abs}
                onChange={(v) => setTol((t) => ({ ...t, qty_tolerance_abs: v }))}
              />
              <TolField
                label="Quantity (%)"
                value={tol.qty_tolerance_pct}
                onChange={(v) => setTol((t) => ({ ...t, qty_tolerance_pct: v }))}
              />
              <TolField
                label="Price (%)"
                value={tol.price_tolerance_pct}
                onChange={(v) => setTol((t) => ({ ...t, price_tolerance_pct: v }))}
              />
              <TolField
                label="Tax (absolute)"
                value={tol.tax_tolerance_abs}
                onChange={(v) => setTol((t) => ({ ...t, tax_tolerance_abs: v }))}
              />
              <TolField
                label="Expected tax rate"
                value={tol.expected_tax_rate}
                onChange={(v) => setTol((t) => ({ ...t, expected_tax_rate: v }))}
                hint="0.18 = 18%"
              />
            </div>
            <p className="mt-3 text-xs text-gray-500">
              A variance inside tolerance is flagged for review rather than closed silently — tolerated
              is not the same as correct.
            </p>
          </Card>

          <Card title={`Row errors (${run.error_row_count})`} description="These rows still load, flagged as incomplete.">
            {run.validation_errors.length === 0 ? (
              <p className="text-sm text-gray-500">No row-level problems found.</p>
            ) : (
              <ul className="max-h-80 space-y-2 overflow-y-auto">
                {run.validation_errors.slice(0, 40).map((e: RowError, i) => (
                  <li key={i} className="text-xs">
                    <span className="font-medium text-gray-700">Row {e.row_number}</span>
                    <span className="text-gray-500"> — {e.message}</span>
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


function TolField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  hint?: string
}) {
  return (
    <label className="block">
      <span className="text-xs text-gray-600">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-teal-600 focus:outline-none"
      />
      {hint && <span className="mt-0.5 block text-[11px] text-gray-400">{hint}</span>}
    </label>
  )
}
