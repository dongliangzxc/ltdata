import axios from 'axios'
import { message } from 'antd'

const api = axios.create({
  baseURL: '/api',
  timeout: 600000,
})

// 请求拦截：自动携带 token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      localStorage.removeItem('auth_user')
      window.location.href = '/login'
      return Promise.reject(err)
    }
    const msg = err.response?.data?.detail || err.response?.data?.message || err.message || '请求失败'
    message.error(msg)
    return Promise.reject(err)
  }
)

export default api

export type PermissionKey = 'data_management' | 'processing_workbench' | 'product_management'

export interface UserProfile {
  id: number
  username: string
  name: string | null
  phone: string | null
  email: string | null
  is_active: number
  is_admin: number
  permissions: PermissionKey[]
  category_permissions: string[]
  created_at: string
  updated_at?: string | null
  last_login_at?: string | null
}

export type ManagedUser = UserProfile

export interface CreateUserPayload {
  username: string
  password: string
  name?: string | null
  phone?: string | null
  email?: string | null
  is_active?: number
  is_admin?: number
  permissions?: PermissionKey[]
  category_permissions?: string[]
}

export interface UpdateUserPayload {
  name?: string | null
  phone?: string | null
  email?: string | null
  is_active?: number
  is_admin?: number
  permissions?: PermissionKey[]
  category_permissions?: string[]
}

interface ApiResponse<T> {
  code: number
  data: T
}

export const getMe = () => api.get<ApiResponse<UserProfile>>('/auth/me').then(r => r.data.data)
export const listUsers = (params?: { keyword?: string; is_active?: number; permission?: PermissionKey }) =>
  api.get<ApiResponse<ManagedUser[]>>('/users', { params }).then(r => r.data.data)
export const createUser = (payload: CreateUserPayload) => api.post<ApiResponse<ManagedUser>>('/users', payload).then(r => r.data.data)
export const updateUser = (id: number, payload: UpdateUserPayload) => api.patch<ApiResponse<ManagedUser>>(`/users/${id}`, payload).then(r => r.data.data)
export const resetUserPassword = (id: number, password: string) =>
  api.post<ApiResponse<{ id: number }>>(`/users/${id}/reset-password`, { password }).then(r => r.data.data)

// ─── Upload ────────────────────────────────────────────────
export const uploadFile = (formData: FormData) =>
  api.post('/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

interface UploadFileItem {
  id: number
  filename: string
  platform: string | null
  month_range: string | null
  row_count: number
  status: string
  template_id: number | null
  uploaded_at: string
  data_region: string | null
  data_year: number | null
  data_month: number | null
}

export const listUploadFiles = (params?: {
  data_region?: string
  data_year?: number
}) => api.get<UploadFileItem[]>('/upload/files', { params })

export const deleteUploadFile = (fileId: number) => api.delete(`/upload/files/${fileId}`)

export const downloadUploadFile = (fileId: number) =>
  api.get(`/upload/files/${fileId}/download`, { responseType: 'blob' })

export interface UploadDownloadJob {
  job_id: number
  file_id: number
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  filename: string | null
  download_url: string | null
  error_msg: string | null
  created_at: string | null
  finished_at: string | null
}

export const createUploadDownloadJob = (fileId: number) =>
  api.post<UploadDownloadJob>(`/upload/files/${fileId}/download-jobs`)

export const listUploadDownloadJobs = (params?: { file_ids?: number[] }) =>
  api.get<UploadDownloadJob[]>('/upload/download-jobs', {
    params: params?.file_ids?.length ? { file_ids: params.file_ids.join(',') } : undefined,
  })

export const getUploadDownloadJob = (jobId: number) =>
  api.get<UploadDownloadJob>(`/upload/download-jobs/${jobId}`)

export const getUploadDownloadJobUrl = (jobId: number) => `/api/upload/download-jobs/${jobId}/download`

// ─── Raw Data ──────────────────────────────────────────────
const rawDataRequestConfig = (params: Record<string, unknown>) => ({
  params,
  paramsSerializer: {
    serialize: (rawParams: Record<string, unknown>) => {
      const searchParams = new URLSearchParams()
      Object.entries(rawParams).forEach(([key, value]) => {
        if (value == null || value === '') return
        if (Array.isArray(value)) {
          value.forEach(item => {
            if (item != null && item !== '') searchParams.append(key, String(item))
          })
        } else {
          searchParams.append(key, String(value))
        }
      })
      return searchParams.toString()
    },
  },
})

export const listRawData = (params: Record<string, unknown>) => api.get('/rawdata', rawDataRequestConfig(params))

export const getRawStats = (params: Record<string, unknown>) => api.get('/rawdata/stats', rawDataRequestConfig(params))

export const getRawFilters = () => api.get('/rawdata/filters')

export const exportRawData = (params: Record<string, unknown>) =>
  api.get('/rawdata/export', { ...rawDataRequestConfig(params), responseType: 'blob' })

// ─── Clean ─────────────────────────────────────────────────
export interface CleanJobItem {
  id: number
  file_ids: number[]
  rules: Record<string, unknown>
  status: string
  row_in: number
  row_out: number
  row_filtered: number
  dispatch_batch_id?: number | null
  dispatch_category_code?: string | null
  task_name?: string | null
  category_code?: string | null
  platform?: string | null
  month?: number | null
  source_scope?: Record<string, unknown> | null
  pending_count?: number | null
  disputed_count?: number | null
  confirmed_count?: number | null
  publishable_count?: number | null
  scope_desc?: string | null
  created_at: string
}

export type CleanJobListView = 'active' | 'archived' | 'all'

export interface CleanPoolCategoryItem {
  category_code: string
  category_name: string | null
  platform: string | null
  current_batch_count: number
  pending_count: number
  active_job_count: number
}

export interface CleanMonthlyPoolItem {
  category_code: string
  category_name: string | null
  platform: string | null
  month: number
  dispatched_count: number
  pending_count: number
  queued_count: number
  existing_job_id: number | null
  existing_job_name: string | null
  existing_job_status: string | null
}

export interface UpsertMonthlyCleanTaskPayload {
  category_code: string
  platform: string
  month: number
  rules?: Record<string, unknown>
  force_reclean?: boolean
}

export interface UpsertMonthlyCleanTaskResponse {
  job: CleanJobItem
  snapshot_count: number
  action: 'created' | 'appended'
  match_status: string
}

export interface CreateCleanTaskPayload {
  category_code: string
  platform?: string | null
  dispatch_batch_id?: number
  task_name?: string
  rules?: Record<string, unknown>
}

export interface CreateCleanTaskResponse {
  job: CleanJobItem
  snapshot_count: number
  match_status: string
}

export type RerunCleanTaskResult = {
  clean_job_id: number
  row_out: number
  filtered_count: number
  matched_count: number
  restored_confirmed_count: number
  restored_review_count?: number
  pending_count: number
}

export const runCleanJob = (payload: {
  file_ids: number[]
  rules: Record<string, unknown>
  dispatch_batch_id?: number
  dispatch_category_code?: string
}) =>
  api.post<CleanJobItem>('/clean/run', payload)

export const runDispatchBatchClean = (payload: {
  dispatch_batch_id: number
  rules: Record<string, unknown>
}) =>
  api.post<{ dispatch_batch_id: number; jobs: CleanJobItem[] }>('/clean/run-dispatch-batch', payload)

export const getCleanPoolSummary = (params?: { dispatch_batch_id?: number }) =>
  api.get<CleanPoolCategoryItem[]>('/clean/pool/summary', { params })

export const getCleanMonthlyPool = (params?: {
  category_code?: string
  platform?: string
  month?: number
  limit?: number
}) => api.get<CleanMonthlyPoolItem[]>('/clean/pool/monthly', { params })

export const upsertMonthlyCleanTask = (payload: UpsertMonthlyCleanTaskPayload) =>
  api.post<UpsertMonthlyCleanTaskResponse>('/clean/tasks/upsert-monthly', payload)

export const createCleanTask = (payload: CreateCleanTaskPayload) =>
  api.post<CreateCleanTaskResponse>('/clean/tasks', payload)

export const listCleanJobs = (params?: {
  category_code?: string
  platform?: string
  month?: number
  view?: CleanJobListView
  limit?: number
  offset?: number
}) => api.get<CleanJobItem[]>('/clean/jobs', { params })

export const deleteCleanJob = (jobId: number) =>
  api.delete<CleanJobItem>(`/clean/jobs/${jobId}`)

export const previewCleanJob = (jobId: number, params?: Record<string, unknown>) =>
  api.get(`/clean/jobs/${jobId}/preview`, { params })

export const rerunCleanTaskWithCurrentRules = (cleanJobId: number) =>
  api.post<RerunCleanTaskResult>(`/clean/tasks/${cleanJobId}/rerun-with-current-rules`)

export interface InterventionRuleConditions extends Record<string, unknown> {
  brand_in?: string[]
  item_name_contains_any?: string[]
  item_name_not_contains_any?: string[]
  reference_price?:
    | { op: 'gt' | 'gte' | 'lt' | 'lte'; value: number }
    | { op: 'between'; min: number; max: number }
}

export interface InterventionRuleItem {
  id: number
  name: string
  category_code: string
  action: 'filter' | 'allow'
  priority: number
  conditions: InterventionRuleConditions
  summary: string
  is_active: number
  created_at: string
  updated_at?: string | null
}

export const listInterventionRules = (params?: { category_code?: string }) =>
  api.get<InterventionRuleItem[]>('/rules/intervention-rules', { params })

export const createInterventionRule = (payload: {
  name: string
  category_code: string
  action: 'filter' | 'allow'
  priority: number
  conditions: Record<string, unknown>
}) =>
  api.post<InterventionRuleItem>('/rules/intervention-rules', payload)

type UpdateInterventionRulePayload = Partial<Pick<
  InterventionRuleItem,
  'name' | 'action' | 'priority' | 'conditions' | 'is_active'
>>

export const updateInterventionRule = (id: number, payload: UpdateInterventionRulePayload) =>
  api.patch<InterventionRuleItem>(`/rules/intervention-rules/${id}`, payload)

export const deleteInterventionRule = (id: number) =>
  api.delete(`/rules/intervention-rules/${id}`)

// ─── Dispatch ──────────────────────────────────────────────
export interface DispatchCategoryPlatformStat {
  platform: string | null
  count: number
}

export interface DispatchCategoryStat {
  category_code: string
  category_name: string | null
  count: number
  platforms?: DispatchCategoryPlatformStat[]
}

export interface DispatchRuleStat {
  rule_id: number
  category_code: string | null
  category_name: string | null
  field: string | null
  match_type: string | null
  value: string | null
  item_name_keyword: string | null
  platform: string | null
  priority: number | null
  is_active: number | null
  count: number
  assigned_count?: number
}

export interface DispatchBatchStatsResponse {
  batch_id: number
  total_rows: number | null
  dispatched_rows: number | null
  unmatched_rows: number | null
  categories: DispatchCategoryStat[]
  rules: DispatchRuleStat[]
}

export interface DispatchUnmatchedRow {
  id: number
  item_id: string | null
  item_name: string | null
  platform: string | null
  month: number | null
  category_lv1: string | null
  category_lv2: string | null
  category_lv3: string | null
  brand_raw: string | null
  shop_name: string | null
  price: number | null
  sales_qty: number | null
  sales_amount: number | null
}

export interface DispatchUnmatchedResponse {
  total: number
  page: number
  page_size: number
  items: DispatchUnmatchedRow[]
}

export const runDispatch = (fileId: number, categoryCode?: string) =>
  api.post('/dispatch/run', categoryCode ? { file_id: fileId, category_code: categoryCode } : { file_id: fileId })

export const enqueueDispatchCategoryForClean = (batchId: number, categoryCode: string) =>
  api.post<{
    dispatch_batch_id: number
    category_code: string
    dispatch_count: number
    pending_count: number
    queued_count: number
  }>(`/dispatch/batches/${batchId}/categories/${categoryCode}/enqueue-clean`)

export const listDispatchBatches = (params?: Record<string, unknown>) =>
  api.get('/dispatch/batches', { params })

export const getDispatchBatchStats = (batchId: number) =>
  api.get<DispatchBatchStatsResponse>(`/dispatch/batches/${batchId}/stats`)

export const listDispatchUnmatched = (batchId: number, params?: { page?: number; page_size?: number; keyword?: string }) =>
  api.get<DispatchUnmatchedResponse>(`/dispatch/batches/${batchId}/unmatched`, { params })

export interface DispatchExportJob {
  job_id: number
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  category_code: string | null
  platform: string | null
  month: number | null
  months: number[]
  filename: string | null
  download_url: string | null
  error_msg: string | null
  created_at: string | null
  finished_at: string | null
  downloaders: string[]
  last_download_at: string | null
}

export interface DispatchExportJobsResponse {
  total: number
  items: DispatchExportJob[]
}

export const createDispatchExportJob = (params: { category_code?: string; platform?: string | null; month?: number; months?: number[] }) =>
  api.post('/dispatch/export', {
    ...(params.category_code ? { category_code: params.category_code } : {}),
    ...(params.platform ? { platform: params.platform } : {}),
    ...(params.months && params.months.length > 0 ? { months: params.months } : {}),
    ...(params.month && (!params.months || params.months.length === 0) ? { month: params.month } : {}),
  })

export const listDispatchExportJobs = (params?: { page?: number; page_size?: number }) =>
  api.get<DispatchExportJobsResponse>('/dispatch/export/jobs', { params })

export const getDispatchExportJob = (jobId: number) =>
  api.get<DispatchExportJob>(`/dispatch/export/jobs/${jobId}`)

export const downloadDispatchExport = (token: string) =>
  api.get(`/dispatch/export/download/${token}`, { responseType: 'blob' })

export const deleteDispatchExportJob = (jobId: number) =>
  api.delete(`/dispatch/export/jobs/${jobId}`)

export const listDispatchRules = (params?: Record<string, unknown>) =>
  api.get('/dispatch/rules', { params })

export const createDispatchRule = (data: unknown) =>
  api.post('/dispatch/rules', data)

export const updateDispatchRule = (id: number, data: unknown) =>
  api.put(`/dispatch/rules/${id}`, data)

export const deleteDispatchRule = (id: number) =>
  api.delete(`/dispatch/rules/${id}`)

// ─── Dispatch: 批量补分发 ────────────────────────────────────
export interface DispatchRedispatchItem {
  id: number
  batch_id: number
  file_id: number | null
  filename: string | null
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
  new_batch_id: number | null
  category_count: number | null
  dispatched_rows: number | null
  unmatched_rows: number | null
  error_msg: string | null
  finished_at: string | null
}

export interface DispatchRedispatchJob {
  id: number
  category_code: string
  category_name: string | null
  skip_contained: number
  status: 'pending' | 'running' | 'done' | 'error'
  total_batches: number
  done_batches: number
  success_batches: number
  failed_batches: number
  skipped_batches: number
  error_msg: string | null
  created_by: string | null
  created_at: string | null
  finished_at: string | null
  items?: DispatchRedispatchItem[]
}

export interface DispatchRedispatchJobsResponse {
  total: number
  items: DispatchRedispatchJob[]
}

export const createDispatchRedispatchJob = (params: { batch_ids: number[]; category_code: string; skip_contained?: boolean }) =>
  api.post<{ job_id: number; status: string }>('/dispatch/redispatch', {
    batch_ids: params.batch_ids,
    category_code: params.category_code,
    skip_contained: params.skip_contained ?? false,
  })

export const listDispatchRedispatchJobs = (params?: { page?: number; page_size?: number }) =>
  api.get<DispatchRedispatchJobsResponse>('/dispatch/redispatch/jobs', { params })

export const getDispatchRedispatchJob = (jobId: number) =>
  api.get<DispatchRedispatchJob>(`/dispatch/redispatch/jobs/${jobId}`)

// ─── Export ────────────────────────────────────────────────
export type TriggerExportPayload =
  | { clean_job_id: number; filename_prefix: string }
  | { months: number[]; category_code: string; platforms: string[]; filename_prefix: string }

export interface ExportJobItem {
  id: number
  clean_job_id: number | null
  months: number[] | null
  category_code: string | null
  platforms: string[] | null
  filename_prefix: string
  status: 'pending' | 'running' | 'done' | 'error'
  filename: string | null
  token: string | null
  rows: number | null
  pending_rows: number | null
  error_msg: string | null
  created_at: string
}

export interface ExportFilterOption {
  months: number[]
  platforms: string[]
  categories: { code: string; name: string }[]
}

export const triggerExport = (payload: TriggerExportPayload) => api.post('/export', payload)

export const listExportJobs = (clean_job_id?: number) =>
  api.get<{ data: ExportJobItem[] }>('/export/jobs', { params: clean_job_id != null ? { clean_job_id } : {} })

export const getExportJob = (job_id: number) =>
  api.get(`/export/jobs/${job_id}`)

export const getExportFilters = () =>
  api.get<ExportFilterOption>('/export/filters')

export const getDownloadUrl = (token: string) => `/api/export/download/${token}`

// ─── Metadata ──────────────────────────────────────────────
export const importMetadata = (formData: FormData) =>
  api.post('/metadata/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const previewMetadata = (formData: FormData) =>
  api.post('/metadata/preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listMetadata = (params: Record<string, unknown>) => api.get('/metadata', { params })

export type MetadataSpecPayload = {
  category_code: string
  spec_name: string
  spec_type: string
  spec_values?: string | null
  required?: boolean
  decimal_places?: number | null
  single_select?: boolean
}

export const createMetadata = (data: MetadataSpecPayload) => api.post('/metadata', data)
export const updateMetadata = (id: number, data: unknown) => api.put(`/metadata/${id}`, data)
export const deleteMetadata = (id: number) => api.delete(`/metadata/${id}`)
export const downloadMetadataTemplate = () =>
  api.get('/metadata/template', { responseType: 'blob' })

export type ModelSpecPayload = {
  spec_name: string
  spec_value?: string | null
}

export type ModelItem = {
  id: number
  brand_code: string
  model_code: string | null
  category_code?: string | null
  category_name?: string | null
  brand_name?: string | null
  model_name?: string | null
  launch_year?: number | null
  launch_month?: number | null
  launch_week?: number | null
  launch_price?: number | null
  url?: string | null
  status: string
  operator?: string | null
  specs: ModelSpecPayload[]
  aliases: { id: number; alias_code: string }[]
  created_at?: string
  updated_at?: string
}

export type CreateModelPayload = {
  brand_code: string
  model_code?: string | null
  category_code?: string | null
  brand_name?: string | null
  model_name?: string | null
  launch_year?: number | null
  launch_month?: number | null
  launch_week?: number | null
  launch_price?: number | null
  url?: string | null
  status?: string
  operator?: string | null
  specs?: ModelSpecPayload[]
}

// ─── Models ────────────────────────────────────────────────
export const importModels = (formData: FormData) =>
  api.post('/models/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const previewModels = (formData: FormData) =>
  api.post('/models/preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listModels = (params: Record<string, unknown>) =>
  api.get<PaginatedResponse<ModelItem>>('/models', { params })
export const getModelDetail = (id: number) => api.get<ModelItem>(`/models/${id}`)
export const createModel = (data: CreateModelPayload) => api.post<ModelItem>('/models', data)
export const updateModel = (id: number, data: CreateModelPayload) => api.put<ModelItem>(`/models/${id}`, data)
export const deleteModel = (id: number) => api.delete(`/models/${id}`)
export const downloadModelTemplate = () =>
  api.get('/models/template', { responseType: 'blob' })
export const listModelAliases = (modelId: number) =>
  api.get(`/models/${modelId}/aliases`)
export const addModelAlias = (modelId: number, aliasCode: string) =>
  api.post(`/models/${modelId}/aliases`, { alias_code: aliasCode })
export const deleteModelAlias = (modelId: number, aliasId: number) =>
  api.delete(`/models/${modelId}/aliases/${aliasId}`)

// ── 禁用 / 启用 ──────────────────────────────────────────────
export const disableMatch = (matchId: number, reason?: string) =>
  api.patch(`/match/${matchId}/disable`, { reason })

export const enableMatch = (matchId: number) =>
  api.patch(`/match/${matchId}/enable`)

export const avgPriceDisable = (cleanJobId: number, threshold: number) =>
  api.post(`/match/${cleanJobId}/avg-price-disable`, { threshold })

export const listDisabled = (cleanJobId: number, page = 1, pageSize = 20) =>
  api.get(`/match/${cleanJobId}/disabled`, { params: { page, page_size: pageSize } })

// ─── Match ─────────────────────────────────────────────────
export const runMatch = (clean_job_id: number) =>
  api.post('/match/run', { clean_job_id })
export const getMatchProgress = (clean_job_id: number) =>
  api.get(`/match/progress/${clean_job_id}`)
export const getMatchSummary = (clean_job_id: number) =>
  api.get(`/match/${clean_job_id}/summary`)
export const listPendingMatches = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get(`/match/${clean_job_id}/pending`, { params })
export const listReviewedMatches = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get<PaginatedResponse<ReviewedMatchResultOut>>(`/match/${clean_job_id}/reviewed`, { params })
export const updateMatchCoefficient = (match_id: number, coefficient: number | null) =>
  api.patch<ReviewedMatchResultOut>(`/match/${match_id}/coefficient`, { coefficient })
export const updateMatchPrice = (match_id: number, adjusted_price: number | null) =>
  api.patch<ReviewedMatchResultOut>(`/match/${match_id}/price`, { adjusted_price })
export const confirmMatch = (
  match_id: number,
  data: { model_id?: number; excluded?: boolean; disputed?: boolean; reason?: string }
) => api.put(`/match/confirm/${match_id}`, data)

export type BatchConfirmFilter = {
  tab: 'text_only' | 'pending'
  keyword?: string | null
  search_by?: 'item_name' | 'brand_raw' | 'brand_code'
  category_name?: string | null
  sort_by?: 'default' | 'sales_qty_desc' | 'sales_qty_asc'
}

export type BatchConfirmPayload =
  | { mode: 'ids'; ids: number[]; model_id: number }
  | { mode: 'filter'; filter: BatchConfirmFilter; model_id: number }

export type BatchConfirmFailure = {
  id: number
  item_name: string | null
  reason: string
}

export type BatchConfirmResult = {
  total: number
  matched_total: number
  truncated: boolean
  success: number
  failed: number
  failures: BatchConfirmFailure[]
}

export type BatchConfirmPreview = {
  total_valid: number
  total_invalid: number
  candidate_distribution: { brand_code: string; model_code: string; count: number }[]
}

export const batchConfirmMatch = (clean_job_id: number, payload: BatchConfirmPayload) =>
  api.post<BatchConfirmResult>(`/match/${clean_job_id}/batch-confirm`, payload)

export const previewBatchConfirmMatch = (clean_job_id: number, filter: BatchConfirmFilter) =>
  api.get<BatchConfirmPreview>(`/match/${clean_job_id}/batch-confirm/preview`, { params: filter })

export interface TransferNoticeOut {
  clean_job_id: number
  new_count: number
  latest_transfer_at: string | null
  checked_at: string
}

export const getTransferNotice = (cleanJobId: number, since: string) =>
  api.get<TransferNoticeOut>(`/match/${cleanJobId}/transfer-notice`, { params: { since } })

export const revertMatch = (match_id: number) =>
  api.post<MatchResultOut>(`/match/items/${match_id}/revert`)

export interface CleanTaskSearchItem {
  id: number
  task_name: string | null
  category_code: string | null
  category_name: string | null
  platform: string | null
  month: number | null
  status: string
  display_name: string | null
}

export const searchCleanTasks = (params: {
  keyword?: string
  exclude_id?: number
  category_code?: string
  platform?: string
  month?: number
  limit?: number
}) =>
  api.get<CleanTaskSearchItem[]>('/clean/tasks/search', { params })

export const transferMatchItem = (match_id: number, target_clean_job_id: number) =>
  api.post<MatchResultOut>(`/match/items/${match_id}/transfer`, { target_clean_job_id })

export const getMatchReviewDetail = (match_id: number) =>
  api.get<MatchReviewDetail>(`/match/items/${match_id}/review-detail`)

export const previewSameTitleMatches = (matchId: number) =>
  api.get<SameTitlePreview>(`/match/items/${matchId}/same-title-preview`)

export const confirmSameTitleMatches = (matchId: number, payload: { model_id: number; include_statuses?: string[] }) =>
  api.post<SameTitleBatchResult>(`/match/items/${matchId}/same-title-confirm`, payload)

export const excludeSameTitleMatches = (matchId: number, payload: { reason?: string; include_statuses?: string[] }) =>
  api.post<SameTitleBatchResult>(`/match/items/${matchId}/same-title-exclude`, payload)

// ─── Analytics Dashboard ─────────────────────────────────────
export type AnalyticsGroupBy = 'model' | 'brand' | 'category' | 'platform'

export interface AnalyticsSummaryParams {
  year?: number
  month?: number
  brand?: string
  category?: string
  platform?: string
  model_keyword?: string
  item_keyword?: string
  group_by?: AnalyticsGroupBy
  page?: number
  page_size?: number
  sort_by?: string
}

export interface AnalyticsMetricRow {
  sales_qty: number
  corrected_sales_qty: number
  sales_amount: number
  avg_price: number | null
  record_count: number
}

export interface AnalyticsSummaryRow extends AnalyticsMetricRow {
  dimension_key: string
  dimension_name: string
  group_by: AnalyticsGroupBy
}

export interface AnalyticsSummaryResponse {
  totals: AnalyticsMetricRow
  rows: AnalyticsSummaryRow[]
  total: number
  page: number
  page_size: number
}

export interface AnalyticsFiltersResponse {
  years: number[]
  months: number[]
  platforms: string[]
  brands: { brand_code: string; brand_name: string | null }[]
  categories: { category_name: string }[]
}

export interface AnalyticsExportResponse {
  job_id: number
  status: 'pending' | 'running' | 'done' | 'error'
  download_url: string
}

export const getAnalyticsFilters = () =>
  api.get<AnalyticsFiltersResponse>('/analytics/filters')

export const getAnalyticsSummary = (params: AnalyticsSummaryParams) =>
  api.get<AnalyticsSummaryResponse>('/analytics/summary', { params })

export const exportAnalyticsSummary = (params: AnalyticsSummaryParams) =>
  api.get<AnalyticsExportResponse>('/analytics/export/summary', { params })

export const exportAnalyticsDetail = (params: AnalyticsSummaryParams & { fields?: string }) =>
  api.get<AnalyticsExportResponse>('/analytics/export/detail', { params })

export const getAnalyticsDownloadUrl = (token: string) => `/api/analytics/download/${token}`

// ─── Workbench ──────────────────────────────────────────────
export const getWorkbenchFilters = () =>
  api.get('/workbench/filters')
export const queryWorkbenchData = (params: Record<string, unknown>) =>
  api.get('/workbench/data', { params })
export const exportWorkbenchData = (params: Record<string, unknown>) =>
  api.post('/workbench/export', params)
export const getWorkbenchDownloadUrl = (token: string) => `/api/workbench/download/${token}`

export function fetchItemAttrs(publishedItemId: number): Promise<{ attr_name: string; attr_value: string }[]> {
  return api.get<{ attr_name: string; attr_value: string }[]>(`/workbench/item-attrs/${publishedItemId}`).then(r => r.data)
}

export interface WorkbenchExportParams {
  year?: number
  month?: number
  category_name?: string
  platform?: string
  brand_code?: string
  model_code?: string
  item_url?: string
  keyword?: string
  statuses?: string[]
  quarter?: number
}

export function exportWorkbench(params: WorkbenchExportParams) {
  return api.post('/workbench/export', params)
}
export const getWorkbenchExportJob = (jobId: number) =>
  api.get<{
    job_id: number
    status: 'pending' | 'running' | 'done' | 'error'
    progress: number
    download_url: string | null
    error_msg: string | null
  }>(`/workbench/export/jobs/${jobId}`)
export const runPublish = (clean_job_id: number) =>
  api.post('/publish/run', { clean_job_id })
export const listPublishJobs = (clean_job_id?: number) =>
  api.get('/publish/jobs', { params: clean_job_id != null ? { clean_job_id } : {} })

// ─── URL Mappings ───────────────────────────────────────────
export const importUrlMappings = (formData: FormData) =>
  api.post('/url-mappings/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const listUrlMappings = (params: Record<string, unknown>) =>
  api.get('/url-mappings', { params })

export const createUrlMapping = (data: { platform: string; item_id: string; model_id: number; price?: number }) =>
  api.post('/url-mappings', data)

export const updateUrlMapping = (id: number, data: { platform: string; item_id: string; model_id: number; price?: number }) =>
  api.put(`/url-mappings/${id}`, data)

export const deleteUrlMapping = (id: number) =>
  api.delete(`/url-mappings/${id}`)

// ─── Rules - Noise Words ────────────────────────────────────
export const listNoiseWords = (params?: { category_code?: string }) =>
  api.get('/rules/noise-words', { params })

export const createNoiseWord = (payload: { keyword: string; match_field: string; category_code?: string | null }) =>
  api.post('/rules/noise-words', payload)

export const toggleNoiseWord = (id: number) =>
  api.patch(`/rules/noise-words/${id}`)

export const deleteNoiseWord = (id: number) =>
  api.delete(`/rules/noise-words/${id}`)

// ─── Rules - Brand Aliases ──────────────────────────────────
export const listBrandAliases = () =>
  api.get('/rules/brand-aliases')

export const createBrandAlias = (payload: { alias_name: string; brand_code: string }) =>
  api.post('/rules/brand-aliases', payload)

export const importBrandAliases = (formData: FormData) =>
  api.post('/rules/brand-aliases/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })

export const deleteBrandAlias = (id: number) =>
  api.delete(`/rules/brand-aliases/${id}`)

// ─── Rules - Match Rules ────────────────────────────────────
export const listMatchRules = () =>
  api.get('/rules/match-rules')

export const createMatchRule = (payload: {
  keyword: string; match_type: string; model_id: number; priority: number
}) => api.post('/rules/match-rules', payload)

export const updateMatchRule = (id: number, payload: Record<string, unknown>) =>
  api.patch(`/rules/match-rules/${id}`, payload)

export const deleteMatchRule = (id: number) =>
  api.delete(`/rules/match-rules/${id}`)

// ─── Rules - Filtered Items ─────────────────────────────────
export type FilteredItemOut = {
  id: number
  raw_data_id: number
  clean_job_id: number
  matched_keyword: string | null
  intervention_rule_id: number | null
  intervention_rule_name: string | null
  matched_reason: string | null
  item_name: string | null
  item_url: string | null
  item_image: string | null
  brand_raw: string | null
  shop_name: string | null
  platform: string | null
  item_id: string | null
  price: number | null
  sales_qty: number | null
  sales_amount: number | null
  created_at: string | null
}

export const listFilteredItems = (params: Record<string, unknown>) =>
  api.get<PaginatedResponse<FilteredItemOut>>('/rules/filtered-items', { params })

export const recoverFilteredItem = (id: number) =>
  api.post<{ recovered: number }>(`/rules/filtered-items/${id}/recover`)

export const recoverFilteredItemsBatch = (ids: number[]) =>
  api.post('/rules/filtered-items/recover-batch', { ids })

// ─── Rules - Attr Rules ─────────────────────────────────────
export const listAttrRuleCategories = () =>
  api.get('/rules/attr-rules/categories')

export const listAttrRules = (params?: { category_code?: string }) =>
  api.get('/rules/attr-rules', { params })

export const createAttrRule = (payload: {
  keyword: string
  match_type: string
  attr_name: string
  attr_value: string
  category_code?: string | null
  priority: number
}) => api.post('/rules/attr-rules', payload)

export const updateAttrRule = (id: number, payload: Record<string, unknown>) =>
  api.patch(`/rules/attr-rules/${id}`, payload)

export const deleteAttrRule = (id: number) =>
  api.delete(`/rules/attr-rules/${id}`)

export const applyAttrRules = (match_job_id: number) =>
  api.post('/rules/attr-rules/apply', { match_job_id })

// ─── Match - Missing Attrs ──────────────────────────────────
export const listMissingAttrs = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get(`/match/${clean_job_id}/missing-attrs`, { params })

// ─── Historical Confirmed Results ─────────────────────────────
export interface HistoricalImportError {
  row: number
  reason: string
}

export interface HistoricalImportResult {
  success: number
  created: number
  updated: number
  errors: HistoricalImportError[]
  import_batch: string
}

export interface HistoricalImportStats {
  total_rows: number
  importable_rows: number
  missing_required_rows: number
  missing_model_rows: number
  auto_create_model_count: number
}

export interface HistoricalImportPreview {
  temp_file_id: string
  filename: string
  sheets: string[]
  sheet_name: string
  columns: string[]
  standard_fields: Record<string, string>
  mapping: Record<string, string>
  category_code: string | null
  issues: string[]
  total_rows: number
  stats: HistoricalImportStats
  preview: Record<string, string | null>[]
}

export interface HistoricalConfirmPayload {
  temp_file_id: string
  sheet_name: string
  mapping: Record<string, string>
  category_code?: string | null
}

export interface HistoricalBatchItem {
  batch: string
  count: number
  updated_at: string | null
}

export interface HistoricalMappingItem {
  id: number
  platform: string
  item_id: string | null
  item_url: string | null
  item_name: string
  brand_raw: string | null
  brand_code_raw: string | null
  model_text: string | null
  model_type: string | null
  model_id: number | null
  model_code: string | null
  standard_model_name: string | null
  category_code: string | null
  category_name_raw: string | null
  year: number
  month_num: number
  month: string
  week: string | null
  sales_qty: number | null
  price: number | null
  sales_amount: number | null
  import_batch: string | null
  match_key_type: string
  updated_at: string | null
}

export interface HistoricalMappingParams {
  platform?: string
  import_batch?: string
  category_code?: string
  model_keyword?: string
  item_keyword?: string
  month?: string
  page?: number
  page_size?: number
}

export const importHistoricalMappings = (formData: FormData) =>
  api.post<HistoricalImportResult>('/historical/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const parseHistoricalImport = (formData: FormData) =>
  api.post<HistoricalImportPreview>('/historical/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const previewHistoricalImport = (payload: HistoricalConfirmPayload) =>
  api.post<HistoricalImportPreview>('/historical/preview', payload)

export const confirmHistoricalImport = (payload: HistoricalConfirmPayload) =>
  api.post<HistoricalImportResult>('/historical/confirm', payload)

export const listHistoricalBatches = () =>
  api.get<HistoricalBatchItem[]>('/historical/batches')

export const listHistoricalMappings = (params?: HistoricalMappingParams) =>
  api.get<PaginatedResponse<HistoricalMappingItem>>('/historical/mappings', { params })

export const exportHistoricalMappings = (params?: HistoricalMappingParams) =>
  api.get('/historical/export', { params, responseType: 'blob' })

export const deleteHistoricalMapping = (id: number) =>
  api.delete(`/historical/mappings/${id}`)

export const deleteHistoricalBatch = (importBatch: string) =>
  api.delete('/historical/mappings/batch', { data: { import_batch: importBatch } })

// ─── Rules - Correction Rules ───────────────────────────────
export const listCorrectionRules = (params?: Record<string, unknown>) =>
  api.get('/correction-rules', { params })

export const createCorrectionRule = (payload: Record<string, unknown>) =>
  api.post('/correction-rules', payload)

export const updateCorrectionRule = (id: number, payload: Record<string, unknown>) =>
  api.put(`/correction-rules/${id}`, payload)

export const deleteCorrectionRule = (id: number) =>
  api.delete(`/correction-rules/${id}`)

export const applyCorrectionRules = (cleanJobId: number) =>
  api.post(`/correction-rules/apply/${cleanJobId}`)

// ─── Match Types ────────────────────────────────────────────
export type PriceFlag = 'ok' | 'high' | 'low' | 'no_history'

export interface PaginatedResponse<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface MatchCandidateOut {
  model_id: number
  model_code: string | null
  brand_code: string | null
  match_source: string | null
  score: number
  rank: number
}

export type MatchMetadataSpec = {
  id: number
  spec_name: string
  spec_type: string
  spec_values: string | null
  required: boolean
  decimal_places: number | null
  single_select: boolean
}

export type MatchModelSpec = {
  id: number
  spec_name: string
  spec_value: string | null
}

export type MatchAutoAttr = {
  id: number
  attr_name: string
  attr_value: string
  rule_id: number | null
}

export type SameTitlePreviewItem = {
  id: number
  raw_data_id: number
  item_name: string | null
  item_url: string | null
  brand_raw: string | null
  match_status: string
  model_id: number | null
  model_code: string | null
  brand_code: string | null
  sales_qty: number | null
  actionable: boolean
}

export type SameTitlePreview = {
  total: number
  actionable_count: number
  status_counts: Record<string, number>
  items: SameTitlePreviewItem[]
}

export type SameTitleBatchResult = {
  affected_count: number
  url_mapping_count?: number
  attr_result?: { matched_attrs: number; items_processed: number }
}

export interface MatchResultOut {
  id: number
  clean_job_id: number
  raw_data_id: number
  model_id?: number | null
  match_status: string
  matched_by: string
  match_source?: string | null
  is_disabled?: number
  disable_reason?: string | null
  brand_identified?: number
  price_flag?: PriceFlag | null
  price_ref?: number | null
  price?: number | null
  adjusted_price?: number | null
  sales_coefficient?: number | null
  dispute_reason?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  revertible?: boolean
  item_name?: string | null
  item_url?: string | null
  brand_raw?: string | null
  model_code?: string | null
  brand_code?: string | null
  attr_count?: number
  candidates?: MatchCandidateOut[]
  sales_qty?: number | null
  corrected_sales_qty?: number | null
  adjusted_sales_qty?: number | null
  category_name?: string | null
}

export interface MatchReviewDetail extends MatchResultOut {
  category_code?: string | null
  metadata_specs?: MatchMetadataSpec[]
  model_specs?: MatchModelSpec[]
  match_attrs?: MatchAutoAttr[]
  item_image?: string | null
  platform?: string | null
  item_id?: string | null
  shop_name?: string | null
  ref_price?: number | null
  price?: number | null
  sales_amount?: number | null
  url_mapping?: {
    id: number
    model_id: number | null
    brand_code: string | null
    source: string | null
  } | null
}

export type ReviewedMatchResultOut = MatchResultOut

// ─── Brands ───────────────────────────────────────────────────────────────────
export type CreateBrandPayload = {
  brand_code: string
  brand_name?: string | null
  alias_name?: string | null
}

export type UpdateBrandPayload = {
  brand_name?: string | null
  alias_name?: string | null
}

export type BrandItem = {
  brand_code: string
  brand_name: string | null
  original_brand_name: string | null
  category_codes: string[]
  model_count: number
  alias_count: number
  brand_alias_name: string | null
}

export type BrandListResponse = {
  total: number
  page: number
  page_size: number
  items: BrandItem[]
}

export type BrandListParams = {
  keyword?: string
  category_code?: string
  page?: number
  page_size?: number
}

export type BrandAliasItem = {
  id: number
  alias_name: string
  brand_code: string
  is_active: number
}

export const listBrands = (params?: BrandListParams) =>
  api.get<BrandListResponse>('/brands', { params })

export const createBrand = (payload: CreateBrandPayload) =>
  api.post<BrandItem>('/brands', payload)

export const updateBrand = (brandCode: string, payload: UpdateBrandPayload) =>
  api.patch<BrandItem>(`/brands/${encodeURIComponent(brandCode)}`, payload)

export const listBrandAliasesByCode = (brandCode: string) =>
  api.get<BrandAliasItem[]>(`/brands/${brandCode}/aliases`)

export type CreateBrandAliasPayload = {
  alias_name: string
}

export const createBrandAliasForCode = (brandCode: string, payload: CreateBrandAliasPayload) =>
  api.post<BrandAliasItem>(`/brands/${brandCode}/aliases`, payload)

export const updateBrandAliasForCode = (
  brandCode: string,
  aliasId: number,
  payload: { alias_name: string },
) => api.patch<BrandAliasItem>(`/brands/${encodeURIComponent(brandCode)}/aliases/${aliasId}`, payload)

export const deleteBrandAliasById = (brandCode: string, aliasId: number) =>
  api.delete(`/brands/${brandCode}/aliases/${aliasId}`)

// ─── Categories ─────────────────────────────────────────────
export type CategoryTreeNode = {
  id: number
  code: string
  name: string
  parent_code: string | null
  sort_order: number
  children: CategoryTreeNode[]
}

export const listCategories = () =>
  api.get('/categories')

export const fetchCategories = () =>
  api.get<{ id: number; code: string; name: string }[]>('/categories').then(r => r.data)

export const fetchAllCategories = () =>
  api.get<{ id: number; code: string; name: string }[]>('/categories/all').then(r => r.data)

export const getCategoryTree = () =>
  api.get<CategoryTreeNode[]>('/categories/tree')

export const createCategory = (data: { code: string; name: string; parent_code?: string | null; sort_order?: number }) =>
  api.post('/categories', data)

export const updateCategory = (id: number, data: { name?: string; parent_code?: string | null; sort_order?: number }) =>
  api.put(`/categories/${id}`, data)

export const deleteCategory = (id: number) =>
  api.delete(`/categories/${id}`)

// ─── Upload Templates ──────────────────────────────────────
export const getUploadHeaders = (formData: FormData) =>
  api.post<{
    temp_file_id: string
    filename: string
    columns: string[]
    suggested_template: {
      id: number
      name: string
      platform: string | null
      mapping: Record<string, string>
      ignore_columns: string[]
    } | null
    match_score: number
  }>('/upload/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const confirmUpload = (payload: {
  temp_file_id: string
  mapping: Record<string, string>
  ignore_columns: string[]
  save_template_name?: string
  template_id?: number
  data_region?: string
  data_year?: number
}) => api.post('/upload/confirm', payload, { timeout: 600000 })

export interface UploadConfirmJobResponse extends Record<string, unknown> {
  job_id: number
  file_id: number | null
  filename: string | null
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  stage: string | null
  stage_label: string | null
  progress: number
  total_rows: number | null
  processed_rows: number | null
  inserted_rows: number | null
  skipped_rows: number | null
  error_msg: string | null
  created_at?: string
  finished_at?: string | null
  platform?: string
  month_range?: string
  row_count?: number
  inserted?: number
  skipped?: number
  preview?: Record<string, unknown>[]
}

export const getUploadConfirmJob = (jobId: number) =>
  api.get<UploadConfirmJobResponse>(`/upload/confirm/jobs/${jobId}`)

export const cancelUploadConfirmJob = (jobId: number) =>
  api.post<UploadConfirmJobResponse>(`/upload/confirm/jobs/${jobId}/cancel`)

export const deleteUploadConfirmJob = (jobId: number) =>
  api.delete(`/upload/confirm/jobs/${jobId}`)

export const listUploadConfirmJobs = (params?: { status?: string; limit?: number }) =>
  api.get<UploadConfirmJobResponse[]>('/upload/confirm/jobs', { params })

export const listUploadTemplates = () =>
  api.get<Array<{
    id: number
    name: string
    platform: string | null
    col_fingerprint: string | null
    mapping: Record<string, string>
    ignore_columns: string[] | null
    is_builtin: number
    updated_at: string | null
  }>>('/upload/templates')

export const createUploadTemplate = (data: {
  name: string
  platform?: string | null
  mapping: Record<string, string>
  ignore_columns: string[]
}) => api.post('/upload/templates', data)

export const updateUploadTemplate = (id: number, data: {
  name: string
  platform?: string | null
  mapping: Record<string, string>
  ignore_columns: string[]
}) => api.put(`/upload/templates/${id}`, data)

export const deleteUploadTemplate = (id: number) =>
  api.delete(`/upload/templates/${id}`)

// ─── P10: Module Import (Headers + Confirm) ────────────────────────────────

export const getAttrRuleHeaders = (formData: FormData) =>
  api.post<{
    temp_file_id: string
    filename: string
    columns: string[]
    suggested_template: {
      id: number
      name: string
      mapping: Record<string, string>
      ignore_columns: string[]
    } | null
    match_score: number
  }>('/rules/attr-rules/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const confirmAttrRuleImport = (payload: {
  temp_file_id: string
  mapping: Record<string, string>
  ignore_columns: string[]
  category_code: string
  save_template_name?: string
}) => api.post<{ inserted: number; skipped: number; errors: string[] }>(
  '/rules/attr-rules/confirm', payload
)

export const getModelHeaders = (formData: FormData) =>
  api.post<{
    temp_file_id: string
    filename: string
    columns: string[]
    suggested_template: {
      id: number
      name: string
      mapping: Record<string, string>
      ignore_columns: string[]
    } | null
    match_score: number
  }>('/models/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const confirmModelImport = (payload: {
  temp_file_id: string
  mapping: Record<string, string>
  ignore_columns: string[]
  category_code: string
  save_template_name?: string
}) => api.post<{
  models_inserted: number
  models_updated: number
  specs_inserted: number
  aliases_inserted: number
  errors: string[]
}>('/models/confirm', payload)

export const getUrlMappingHeaders = (formData: FormData) =>
  api.post<{
    temp_file_id: string
    filename: string
    columns: string[]
    suggested_template: {
      id: number
      name: string
      mapping: Record<string, string>
      ignore_columns: string[]
    } | null
    match_score: number
  }>('/url-mappings/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const confirmUrlMappingImport = (payload: {
  temp_file_id: string
  mapping: Record<string, string>
  ignore_columns: string[]
  category_code: string
  save_template_name?: string
}) => api.post<{ inserted: number; updated: number; skipped: number; errors: string[] }>(
  '/url-mappings/confirm', payload
)

// —— /match-results 页面用 ——
export type MatchResultsTab = 'all' | 'pending_review' | 'confirmed'
export type PriceFlagFilter = 'below' | 'above' | 'normal' | 'none'
export type CoefficientFilter = 'with' | 'without'
export interface MatchResultsQuery {
  page?: number
  page_size?: number
  tab?: MatchResultsTab
  clean_job_id?: number
  match_source?: string[]
  price_flag?: PriceFlagFilter
  keyword?: string
  platform?: string
  brand_keyword?: string
  model_keyword?: string
  coefficient_filter?: CoefficientFilter
}
export type MatchResultsSummary = {
  original_price: number | null
  adjusted_price: number | null
  original_sales_qty: number
  adjusted_sales_qty: number
  original_consumption_amount: number
  adjusted_consumption_amount: number
}

export interface MatchResultsResponse {
  total: number
  page: number
  page_size: number
  items: ReviewedMatchResultOut[]
  counts: { all: number; pending_review: number; confirmed: number }
  summary: MatchResultsSummary
}
export const listMatchResults = (params: MatchResultsQuery) =>
  api.get<MatchResultsResponse>('/match/reviewed', {
    params,
    paramsSerializer: {
      // match_source 数组按重复键序列化（axios 1.x）：?match_source=a&match_source=b
      indexes: null,
    },
  })
