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

export const getDownloadUrl = (token: string) => `/api/export/download/${token}`

// ─── Metadata ──────────────────────────────────────────────
export const importMetadata = (formData: FormData) =>
  api.post('/metadata/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listMetadata = (params: Record<string, unknown>) => api.get('/metadata', { params })
export const createMetadata = (data: unknown) => api.post('/metadata', data)
export const updateMetadata = (id: number, data: unknown) => api.put(`/metadata/${id}`, data)
export const deleteMetadata = (id: number) => api.delete(`/metadata/${id}`)

// ─── Models ────────────────────────────────────────────────
export const importModels = (formData: FormData) =>
  api.post('/models/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
export const listModels = (params: Record<string, unknown>) => api.get('/models', { params })
export const getModelDetail = (id: number) => api.get(`/models/${id}`)
export const createModel = (data: unknown) => api.post('/models', data)
export const updateModel = (id: number, data: unknown) => api.put(`/models/${id}`, data)
export const deleteModel = (id: number) => api.delete(`/models/${id}`)

// ─── Match ─────────────────────────────────────────────────
export const runMatch = (clean_job_id: number) =>
  api.post('/match/run', { clean_job_id })
export const getMatchSummary = (clean_job_id: number) =>
  api.get(`/match/${clean_job_id}/summary`)
export const listPendingMatches = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get(`/match/${clean_job_id}/pending`, { params })
export const confirmMatch = (match_id: number, data: { model_id?: number; excluded?: boolean }) =>
  api.put(`/match/confirm/${match_id}`, data)

// ─── Publish ────────────────────────────────────────────────
export const runPublish = (clean_job_id: number) =>
  api.post('/publish/run', { clean_job_id })
export const listPublishJobs = (clean_job_id?: number) =>
  api.get('/publish/jobs', { params: clean_job_id != null ? { clean_job_id } : {} })
