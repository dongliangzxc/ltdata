import type { CleanJobItem, CleanMonthlyPoolItem } from '../../services/api'

export type SupplementTarget = Pick<CleanJobItem, 'id' | 'task_name' | 'category_code' | 'platform' | 'month'>

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
