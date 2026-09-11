import type { ReactNode } from 'react'
import type { ResultStatus } from '../types'

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-gray-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Card({
  title,
  description,
  actions,
  children,
  padded = true,
}: {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  padded?: boolean
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold text-gray-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-gray-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

const STATUS_STYLES: Record<ResultStatus, string> = {
  MATCHED: 'bg-teal-50 text-teal-700 ring-teal-600/20',
  AUTO_CLOSED: 'bg-teal-50 text-teal-700 ring-teal-600/20',
  REVIEW: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  MISMATCH: 'bg-amber-50 text-amber-800 ring-amber-600/25',
  DUPLICATE: 'bg-red-50 text-red-700 ring-red-600/20',
  INCOMPLETE: 'bg-gray-100 text-gray-600 ring-gray-500/20',
}

export const STATUS_LABEL: Record<ResultStatus, string> = {
  MATCHED: 'Matched',
  AUTO_CLOSED: 'Auto-closed',
  REVIEW: 'Review',
  MISMATCH: 'Mismatch',
  DUPLICATE: 'Duplicate',
  INCOMPLETE: 'Incomplete',
}

export function StatusPill({ status }: { status: ResultStatus | string }) {
  const key = status as ResultStatus
  const style = STATUS_STYLES[key] ?? 'bg-gray-100 text-gray-600 ring-gray-500/20'
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${style}`}
    >
      {STATUS_LABEL[key] ?? status}
    </span>
  )
}

export function StatCard({
  label,
  value,
  tone = 'default',
  onClick,
  active,
}: {
  label: string
  value: number | string
  tone?: 'default' | 'good' | 'warn' | 'bad' | 'info'
  onClick?: () => void
  active?: boolean
}) {
  const toneClass = {
    default: 'text-gray-900',
    good: 'text-teal-700',
    info: 'text-blue-700',
    warn: 'text-amber-700',
    bad: 'text-red-700',
  }[tone]

  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      onClick={onClick}
      className={`rounded-lg border bg-white px-4 py-3 text-left shadow-sm transition-colors ${
        active ? 'border-teal-600 ring-1 ring-teal-600' : 'border-gray-200'
      } ${onClick ? 'cursor-pointer hover:border-gray-300' : ''}`}
    >
      <div className={`text-2xl font-semibold tracking-tight ${toneClass}`}>{value}</div>
      <div className="mt-0.5 text-xs text-gray-500">{label}</div>
    </Tag>
  )
}

export function Button({
  children,
  variant = 'primary',
  disabled,
  onClick,
  type = 'button',
  size = 'md',
}: {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  disabled?: boolean
  onClick?: () => void
  type?: 'button' | 'submit'
  size?: 'sm' | 'md'
}) {
  const base =
    'inline-flex items-center justify-center rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50'
  const sizing = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm'
  const variants = {
    primary: 'bg-teal-700 text-white hover:bg-teal-800',
    secondary: 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50',
    ghost: 'text-teal-700 hover:bg-teal-50',
    danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50',
  }[variant]
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${sizing} ${variants}`}>
      {children}
    </button>
  )
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
      <p className="text-sm font-medium text-gray-900">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-md text-sm text-gray-500">{body}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p className="px-1 py-8 text-sm text-gray-500">{label}</p>
}

export function ErrorNote({ title, body, children }: { title: string; body?: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
      <p className="text-sm font-semibold text-red-800">{title}</p>
      {body && <p className="mt-1 text-sm text-red-700">{body}</p>}
      {children}
    </div>
  )
}

export function Th({
  children,
  align = 'left',
}: {
  children?: ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <th
      className={`whitespace-nowrap border-b border-gray-200 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500 ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  )
}

export function Td({
  children,
  align = 'left',
  muted,
}: {
  children: ReactNode
  align?: 'left' | 'right'
  muted?: boolean
}) {
  return (
    <td
      className={`border-b border-gray-100 px-3 py-2 text-sm ${align === 'right' ? 'text-right' : ''} ${
        muted ? 'text-gray-500' : 'text-gray-800'
      }`}
    >
      {children}
    </td>
  )
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function num(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return value
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 4 })
}
