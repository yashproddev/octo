import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ExpectedFormat, UploadFailure, UploadResponse } from '../types'
import { Button, Card, ErrorNote, PageHeader } from '../components/ui'
import { useEffect } from 'react'

export default function Upload() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<UploadFailure | null>(null)
  const [dragging, setDragging] = useState(false)
  const [format, setFormat] = useState<ExpectedFormat | null>(null)

  useEffect(() => {
    api.get<ExpectedFormat>('/schema').then(setFormat).catch(() => undefined)
  }, [])

  async function send(file: File) {
    setBusy(true)
    setFailure(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.upload<UploadResponse>('/ingestion/uploads', form)
      navigate(`/runs/${res.run.id}/mapping`)
    } catch (err) {
      if (err instanceof ApiError && err.detail && typeof err.detail === 'object') {
        setFailure(err.detail as UploadFailure)
      } else {
        setFailure({ message: err instanceof Error ? err.message : 'Upload failed.' })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Upload Dataset"
        subtitle="One row per item, carrying the ordered, received and billed figures together. Column names need not match exactly."
        actions={
          <a href="/api/v1/template.csv" download>
            <Button variant="secondary">Download template</Button>
          </a>
        }
      />

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files?.[0]
          if (file) void send(file)
        }}
        className={`rounded-lg border-2 border-dashed bg-white px-6 py-12 text-center transition-colors ${
          dragging ? 'border-teal-600 bg-teal-50' : 'border-gray-300'
        }`}
      >
        <p className="text-sm font-medium text-gray-900">
          {busy ? 'Processing…' : 'Drop a CSV here'}
        </p>
        <p className="mt-1 text-sm text-gray-500">Maximum 4.5 MB per upload.</p>
        <div className="mt-4 flex justify-center">
          <Button onClick={() => inputRef.current?.click()} disabled={busy}>
            Choose file
          </Button>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void send(file)
            e.target.value = ''
          }}
        />
      </div>

      {failure && (
        <div className="mt-5">
          <ErrorNote title={failure.message} body={failure.hint}>
            {failure.missing_required && failure.missing_required.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-red-800">
                  Missing required columns
                </p>
                <ul className="mt-1 list-inside list-disc text-sm text-red-700">
                  {failure.missing_required.map((f) => (
                    <li key={f}>
                      <code className="rounded bg-red-100 px-1 text-xs">{f}</code>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {failure.mapping && Object.keys(failure.mapping).length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-red-800">
                  Columns we did recognise
                </p>
                <ul className="mt-1 text-sm text-red-700">
                  {Object.values(failure.mapping).map((m) => (
                    <li key={m.canonical_field}>
                      <code className="text-xs">{m.source_column}</code> → {m.canonical_field}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </ErrorNote>
        </div>
      )}

      {format && (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <Card title="Required columns" description="Every one of these must be present.">
            <FieldList fields={format.required} format={format} />
          </Card>
          <Card title="Optional columns" description="Unlock extra checks when supplied.">
            <FieldList fields={format.optional} format={format} />
          </Card>
        </div>
      )}
    </div>
  )
}

function FieldList({
  fields,
  format,
}: {
  fields: ExpectedFormat['required']
  format: ExpectedFormat
}) {
  return (
    <dl className="divide-y divide-gray-100">
      {fields.map((f) => (
        <div key={f.field} className="py-2 first:pt-0 last:pb-0">
          <dt className="flex items-center gap-2">
            <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-800">{f.field}</code>
            <span className="text-[11px] uppercase tracking-wide text-gray-400">{f.type}</span>
          </dt>
          <dd className="mt-1 text-xs text-gray-500">
            {f.description}
            {format.aliases[f.field]?.length > 0 && (
              <span className="mt-0.5 block text-gray-400">
                Also accepts: {format.aliases[f.field].slice(0, 4).join(', ')}
              </span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}
