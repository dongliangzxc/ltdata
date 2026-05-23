import axios from 'axios'
import { message } from 'antd'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
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
      window.location.href = '/login'
      return Promise.reject(err)
    }
    const msg = err.response?.data?.detail || err.response?.data?.message || err.message || '请求失败'
    message.error(msg)
    return Promise.reject(err)
  }
)

export default api

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
  data_month?: number
}) => api.get<UploadFileItem[]>('/upload/files', { params })

export const deleteUploadFile = (fileId: number) => api.delete(`/upload/files/${fileId}`)

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
export const runCleanJob = (payload: {
  file_ids: number[]
  rules: Record<string, unknown>
  dispatch_batch_id?: number
  dispatch_category_code?: string
}) =>
  api.post('/clean/run', payload)

export const listCleanJobs = () => api.get('/clean/jobs')

export const previewCleanJob = (jobId: number, params?: Record<string, unknown>) =>
  api.get(`/clean/jobs/${jobId}/preview`, { params })

// ─── Dispatch ──────────────────────────────────────────────
export interface DispatchCategoryStat {
  category_code: string
  category_name: string | null
  count: number
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

export const runDispatch = (fileId: number) =>
  api.post('/dispatch/run', { file_id: fileId })

export const listDispatchBatches = (params?: Record<string, unknown>) =>
  api.get('/dispatch/batches', { params })

export const getDispatchBatchStats = (batchId: number) =>
  api.get<DispatchBatchStatsResponse>(`/dispatch/batches/${batchId}/stats`)

export const listDispatchUnmatched = (batchId: number, params?: { page?: number; page_size?: number; keyword?: string }) =>
  api.get<DispatchUnmatchedResponse>(`/dispatch/batches/${batchId}/unmatched`, { params })

export const listDispatchRules = (params?: Record<string, unknown>) =>
  api.get('/dispatch/rules', { params })

export const createDispatchRule = (data: unknown) =>
  api.post('/dispatch/rules', data)

export const updateDispatchRule = (id: number, data: unknown) =>
  api.put(`/dispatch/rules/${id}`, data)

export const deleteDispatchRule = (id: number) =>
  api.delete(`/dispatch/rules/${id}`)

// ─── Export ────────────────────────────────────────────────
export const triggerExport = (payload: {
  clean_job_id: number
  filename_prefix: string
}) => api.post('/export', payload)

export const listExportJobs = (clean_job_id?: number) =>
  api.get('/export/jobs', { params: clean_job_id != null ? { clean_job_id } : {} })

export const getExportJob = (job_id: number) =>
  api.get(`/export/jobs/${job_id}`)

export const getDownloadUrl = (token: string) => `/api/export/download/${token}`

// ─── Metadata ──────────────────────────────────────────────
export const importMetadata = (formData: FormData) =>
  api.post('/metadata/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const previewMetadata = (formData: FormData) =>
  api.post('/metadata/preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listMetadata = (params: Record<string, unknown>) => api.get('/metadata', { params })
export const createMetadata = (data: unknown) => api.post('/metadata', data)
export const updateMetadata = (id: number, data: unknown) => api.put(`/metadata/${id}`, data)
export const deleteMetadata = (id: number) => api.delete(`/metadata/${id}`)

// ─── Models ────────────────────────────────────────────────
export const importModels = (formData: FormData) =>
  api.post('/models/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const previewModels = (formData: FormData) =>
  api.post('/models/preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listModels = (params: Record<string, unknown>) => api.get('/models', { params })
export const getModelDetail = (id: number) => api.get(`/models/${id}`)
export const createModel = (data: unknown) => api.post('/models', data)
export const updateModel = (id: number, data: unknown) => api.put(`/models/${id}`, data)
export const deleteModel = (id: number) => api.delete(`/models/${id}`)
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
export const confirmMatch = (match_id: number, data: { model_id?: number; excluded?: boolean }) =>
  api.put(`/match/confirm/${match_id}`, data)

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
  month?: number
  platform?: string
  brand_code?: string
  model_code?: string
  category_name?: string
  keyword?: string
  statuses?: string[]
  year?: number
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
export const listFilteredItems = (params: Record<string, unknown>) =>
  api.get('/rules/filtered-items', { params })

export const recoverFilteredItem = (id: number) =>
  api.post(`/rules/filtered-items/${id}/recover`)

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

// ─── Historical Mappings ─────────────────────────────────────
export const importHistoricalMappings = (formData: FormData) =>
  api.post('/historical/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const listHistoricalBatches = () =>
  api.get<{ batch: string; count: number }[]>('/historical/batches')

export const listHistoricalMappings = (params?: {
  platform?: string
  import_batch?: string
  category_code?: string
  page?: number
  page_size?: number
}) => api.get('/historical/mappings', { params })

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
  sales_coefficient?: number | null
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

export type ReviewedMatchResultOut = MatchResultOut

// ─── Brands ───────────────────────────────────────────────────────────────────
export type BrandItem = {
  brand_code: string
  brand_name: string | null
  model_count: number
  alias_count: number
}

export type BrandAliasItem = {
  id: number
  alias_name: string
  brand_code: string
  is_active: number
}

export const listBrands = () =>
  api.get<BrandItem[]>('/brands')

export const listBrandAliasesByCode = (brandCode: string) =>
  api.get<BrandAliasItem[]>(`/brands/${brandCode}/aliases`)

export const createBrandAliasForCode = (brandCode: string, payload: { alias_name: string }) =>
  api.post<BrandAliasItem>(`/brands/${brandCode}/aliases`, payload)

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
  data_month?: number
}) => api.post('/upload/confirm', payload, { timeout: 300000 })

export interface UploadConfirmJobResponse extends Record<string, unknown> {
  job_id: number
  file_id: number | null
  filename: string | null
  status: 'pending' | 'running' | 'done' | 'error'
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
