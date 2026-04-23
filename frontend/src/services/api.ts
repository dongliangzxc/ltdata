import axios from 'axios'
import { message } from 'antd'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
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
  split_by_platform: boolean
}) => api.post('/export', payload)

export const getDownloadUrl = (token: string) => `/api/export/download/${token}`
