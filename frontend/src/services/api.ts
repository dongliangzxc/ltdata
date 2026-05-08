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

export const listUploadFiles = () => api.get('/upload/files')

export const deleteUploadFile = (fileId: number) => api.delete(`/upload/files/${fileId}`)

// ─── Raw Data ──────────────────────────────────────────────
export const listRawData = (params: Record<string, unknown>) => api.get('/rawdata', { params })

export const getRawStats = (params: Record<string, unknown>) => api.get('/rawdata/stats', { params })

export const getRawFilters = () => api.get('/rawdata/filters')

// ─── Clean ─────────────────────────────────────────────────
export const runCleanJob = (payload: { file_ids: number[]; rules: Record<string, unknown> }) =>
  api.post('/clean/run', payload)

export const listCleanJobs = () => api.get('/clean/jobs')

export const previewCleanJob = (jobId: number, params?: Record<string, unknown>) =>
  api.get(`/clean/jobs/${jobId}/preview`, { params })

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
export const confirmMatch = (match_id: number, data: { model_id?: number; excluded?: boolean }) =>
  api.put(`/match/confirm/${match_id}`, data)

// ─── Workbench ──────────────────────────────────────────────
export const getWorkbenchFilters = () =>
  api.get('/workbench/filters')
export const queryWorkbenchData = (params: Record<string, unknown>) =>
  api.get('/workbench/data', { params })
export const exportWorkbenchData = (params: Record<string, unknown>) =>
  api.post('/workbench/export', params)
export const getWorkbenchDownloadUrl = (token: string) => `/api/workbench/download/${token}`
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
export const listNoiseWords = () =>
  api.get('/rules/noise-words')

export const createNoiseWord = (payload: { keyword: string; match_field: string }) =>
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
  page?: number
  page_size?: number
}) => api.get('/historical/mappings', { params })

export const deleteHistoricalMapping = (id: number) =>
  api.delete(`/historical/mappings/${id}`)

export const deleteHistoricalBatch = (importBatch: string) =>
  api.delete('/historical/mappings/batch', { data: { import_batch: importBatch } })
