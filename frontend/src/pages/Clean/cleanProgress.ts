import type { CleanJobItem, CleanJobProgress } from '../../services/api'

export const processingStatuses = new Set(['queued', 'created', 'cleaning', 'matching', 'processing'])

function isCurrent(job: CleanJobItem, progress: CleanJobProgress): boolean {
  return !job.updated_at || !progress.updated_at || Date.parse(progress.updated_at) >= Date.parse(job.updated_at)
}

export function mergeCleanProgress(jobs: CleanJobItem[], progress: CleanJobProgress[]): CleanJobItem[] {
  const byId = new Map(progress.map(row => [row.id, row]))
  return jobs.map(job => {
    const incoming = byId.get(job.id)
    return incoming && isCurrent(job, incoming) ? { ...job, ...incoming } : job
  })
}

export function finishedCleanJobIds(jobs: CleanJobItem[], progress: CleanJobProgress[]): number[] {
  const busy = new Map(jobs.filter(row => processingStatuses.has(row.status)).map(row => [row.id, row]))
  return progress.filter(row => {
    const job = busy.get(row.id)
    return job && isCurrent(job, row) && !processingStatuses.has(row.status)
  }).map(row => row.id)
}

export function formatCleanProgress(row: CleanJobItem): string {
  const stage = row.progress_stage || (row.status === 'queued' ? '排队中' : '处理中')
  return (row.progress_total ?? 0) > 0
    ? `${stage}：${row.progress_processed ?? 0} / ${row.progress_total} 条`
    : stage
}
