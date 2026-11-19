import type { CleanJobItem, CleanMonthlyPoolItem } from '../../services/api'

export type SupplementTarget = Pick<CleanJobItem, 'id' | 'task_name' | 'category_code' | 'platform' | 'month'>

export function jobSupplementTarget(job: CleanJobItem): SupplementTarget | null {
  const categoryCode = job.category_code || job.dispatch_category_code
  if (!job.id || !categoryCode || !job.platform || !job.month) return null
  if (!['reviewing', 'done', 'published'].includes(job.status)) return null
  const months = job.source_scope?.months
  if (Array.isArray(months) && new Set(months.map(Number)).size > 1) return null
  return {
    id: job.id,
    task_name: job.task_name || job.scope_desc,
    category_code: categoryCode,
    platform: job.platform,
    month: job.month,
  }
}

export function monthlySupplementTarget(row: CleanMonthlyPoolItem): SupplementTarget | null {
  if (!row.existing_job_id || !row.category_code || !row.platform || !row.month) return null
  if (!['reviewing', 'done', 'published'].includes(row.existing_job_status ?? '')) return null
  return {
    id: row.existing_job_id,
    task_name: row.existing_job_name,
    category_code: row.category_code,
    platform: row.platform,
    month: row.month,
  }
}
