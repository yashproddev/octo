export type ResultStatus =
  | 'MATCHED'
  | 'MISMATCH'
  | 'DUPLICATE'
  | 'INCOMPLETE'
  | 'REVIEW'
  | 'AUTO_CLOSED'

export interface Health {
  service: string
  status: 'ok' | 'degraded'
  rule_version: string
  database: { connected: boolean; server?: string; error?: string }
}

export interface FieldDef {
  field: string
  label: string
  type: 'string' | 'number' | 'date'
  description: string
}

export interface ExpectedFormat {
  required: FieldDef[]
  optional: FieldDef[]
  aliases: Record<string, string[]>
  note: string
}

export interface ColumnMatch {
  canonical_field: string
  source_column: string
  match: 'exact' | 'alias' | 'manual' | 'unmapped'
}

export interface IngestionRun {
  id: string
  status: 'UPLOADED' | 'FAILED_VALIDATION' | 'STAGED' | 'NORMALIZED'
  source_filename: string
  row_count: number
  valid_row_count: number
  error_row_count: number
  column_mapping: Record<string, ColumnMatch> | null
  unmapped_columns: string[]
  validation_errors: RowError[]
  normalized_at: string | null
  created_at: string
}

export interface RowError {
  row_number: number
  field: string | null
  source_column: string | null
  value: string | null
  message: string
}

export interface UploadResponse {
  run: IngestionRun
  mapping: Record<string, ColumnMatch>
  unmapped_columns: string[]
  missing_required: string[]
  duplicate_targets: Record<string, string[]>
  preview: { row_number: number; mapped: Record<string, string>; errors: RowError[] }[]
}

export interface UploadFailure {
  message: string
  hint?: string
  expected_format?: ExpectedFormat
  mapping?: Record<string, ColumnMatch>
  missing_required?: string[]
  unmapped_columns?: string[]
}

export interface ReconciliationRun {
  id: string
  ingestion_run_id: string
  rule_version: string
  tolerances: Record<string, string | boolean>
  status: string
  status_counts: Partial<Record<ResultStatus, number>>
  total_exposure: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ResultRow {
  id: string
  system_status: ResultStatus
  current_status: ResultStatus
  explanation: string
  failed_checks: string[]
  unchecked: string[]
  decision_count: number
  row_number: number
  po_number: string | null
  vendor: string | null
  item: string | null
  invoice_number: string | null
  po_quantity: string | null
  grn_quantity: string | null
  invoice_quantity: string | null
  po_unit_price: string | null
  invoice_unit_price: string | null
  tax: string | null
  currency: string | null
  exposure: string | null
}

export interface Finding {
  rule_id: string
  label: string
  passed: boolean
  severity: 'info' | 'review' | 'hard'
  expected: string | null
  actual: string | null
  variance: string | null
  variance_pct: string | null
  tolerance: string | null
  explanation: string
  skipped: boolean
  skip_reason: string | null
}

export interface Decision {
  id: string
  actor: string
  action: string
  from_status: string
  to_status: string
  reason: string | null
  rule_version: string
  is_system: boolean
  decided_at: string
}

export interface ResultDetail {
  id: string
  system_status: ResultStatus
  current_status: ResultStatus
  explanation: string
  snapshot: Record<string, string | null>
  findings: Finding[]
  rule_version: string | null
  tolerances: Record<string, string | boolean> | null
  source_row: { row_number: number; raw_data: Record<string, string>; errors: RowError[] } | null
  decisions: Decision[]
}

export interface DecisionLogRow extends Decision {
  result_id: string
  system_status: ResultStatus | null
  snapshot: Record<string, string | null> | null
}

export interface Overview {
  latest_run: ReconciliationRun | null
  open_exposure: string
  totals: {
    ingestion_runs: number
    reconciliation_runs: number
    results: number
    human_decisions: number
  }
  recent_ingestion_runs: {
    id: string
    source_filename: string
    status: string
    row_count: number
    error_row_count: number
    created_at: string
  }[]
}
