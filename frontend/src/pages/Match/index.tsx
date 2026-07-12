import { useState, useEffect, useRef } from 'react'
import {
  Card, Select, Button, Table, Tag, Space, Typography, Input,
  message, Row, Col, Statistic, Tooltip, Progress, Alert, Popconfirm, InputNumber, Tabs,
  List, Descriptions, Empty, Modal, Image, Checkbox,
} from 'antd'
import { AimOutlined, StopOutlined, CloudUploadOutlined, LoadingOutlined, LinkOutlined, DownloadOutlined, PlusOutlined, UndoOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import {
  listCleanJobs, runMatch, getMatchProgress, getMatchSummary, listPendingMatches,
  confirmMatch, revertMatch, listModels, runPublish, listPublishJobs,
  listReviewedMatches, updateMatchCoefficient, getMatchReviewDetail,
  enableMatch, avgPriceDisable, listDisabled,
  triggerExport, getExportJob, getDownloadUrl,
  getCleanMonthlyPool, rerunCleanTaskWithCurrentRules,
  listFilteredItems, recoverFilteredItem,
  batchConfirmMatch, previewBatchConfirmMatch,
} from '../../services/api'
import type { CleanJobItem, MatchCandidateOut, ReviewedMatchResultOut, PriceFlag, MatchReviewDetail, FilteredItemOut, ModelItem, BatchConfirmFilter, BatchConfirmResult } from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
import ProgressModal from '../../components/ProgressModal'
import AttributeInsightCard from './components/AttributeInsightCard'
import SameTitleBatchActions from './components/SameTitleBatchActions'
import InterventionRuleModal from './components/InterventionRuleModal'
import CreateModelModal from '../../components/CreateModelModal'
import ReselectModal from './components/ReselectModal'

const { Text } = Typography

const priceFlagMeta: Record<PriceFlag, { label: string; color: string }> = {
  ok: { label: '正常', color: 'green' },
  high: { label: '偏高', color: 'red' },
  low: { label: '偏低', color: 'orange' },
  no_history: { label: '无历史', color: 'default' },
}

const formatNumber = (value?: number | null) => (
  value != null ? value.toLocaleString() : '-'
)

const getBaseSalesQty = (row: ReviewedMatchResultOut) => row.corrected_sales_qty ?? row.sales_qty ?? null

const getAdjustedSalesQty = (row: ReviewedMatchResultOut, draftCoefficient?: number | null, hasLocalEdit = false) => {
  if (!hasLocalEdit && row.adjusted_sales_qty != null) return row.adjusted_sales_qty
  const coefficient = hasLocalEdit ? draftCoefficient ?? null : row.sales_coefficient ?? null
  const base = getBaseSalesQty(row)
  return base != null && coefficient != null ? Math.round(base * coefficient) : base
}

const isPlaceholderCode = (value?: string | null) => {
  const normalized = (value ?? '').trim()
  return normalized === '' || /^-+$/.test(normalized)
}

const hasDisplayModel = (brandCode?: string | null, modelCode?: string | null) => (
  !isPlaceholderCode(brandCode) && !isPlaceholderCode(modelCode)
)

const matchSourceMeta = (source?: string | null) => {
  const map: Record<string, { label: string; color: string }> = {
    s0: { label: 'URL映射命中', color: 'blue' },
    historical: { label: '历史库命中', color: 'purple' },
    's0.5': { label: '规则命中', color: 'cyan' },
    s1: { label: '品牌字段匹配', color: 'green' },
    s2: { label: '标题品牌码匹配', color: 'green' },
    s3: { label: '标题品牌名匹配', color: 'green' },
    s4: { label: '型号码兜底匹配', color: 'orange' },
    manual: { label: '人工确认', color: 'blue' },
  }
  return source ? map[source] : undefined
}

const renderMatchSource = (source?: string | null) => {
  const entry = matchSourceMeta(source)
  if (!source) return <Tag color="default">未知</Tag>
  return entry ? <Tag color={entry.color}>{entry.label}</Tag> : <Tag>{source}</Tag>
}

const INVALID_CANDIDATE_CODES = new Set(['', '-', '--'])

const getTopCandidate = (item: PendingItem): MatchCandidateOut | undefined =>
  item.candidates?.slice().sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))[0]

const isCandidateValidForBatch = (item: PendingItem): { ok: boolean; reason?: string } => {
  if (item.brand_identified === 0) return { ok: false, reason: '未识别品牌，请先补充品牌写法' }
  const top = getTopCandidate(item)
  if (!top) return { ok: false, reason: '暂无候选型号' }
  if (!top.brand_code || INVALID_CANDIDATE_CODES.has(top.brand_code)) return { ok: false, reason: '候选品牌码无效' }
  if (!top.model_code || INVALID_CANDIDATE_CODES.has(top.model_code)) return { ok: false, reason: '候选型号码无效' }
  return { ok: true }
}

const statusMeta: Record<string, { label: string; color: string }> = {
  pending: { label: '待确认', color: 'orange' },
  text_only: { label: 'URL待确认', color: 'gold' },
  disputed: { label: '争议', color: 'red' },
  matched: { label: '已匹配', color: 'green' },
  url_matched: { label: '精准匹配', color: 'green' },
  confirmed: { label: '已人工确认', color: 'blue' },
  excluded: { label: '已排除', color: 'default' },
}

const renderMatchStatus = (status?: string | null) => {
  if (!status) return <Tag color="default">未知</Tag>
  const meta = statusMeta[status]
  return meta ? <Tag color={meta.color}>{meta.label}</Tag> : <Tag>{status}</Tag>
}

type MatchSummary = {
  clean_job_id: number
  total: number
  url_matched: number
  precise_matched?: number
  matched: number
  text_only: number
  pending: number
  confirmed: number
  excluded: number
  disputed: number
  disabled: number
  unidentified_brand?: number
}

type PendingItem = {
  id: number
  raw_data_id: number
  item_name: string
  item_url?: string | null
  brand_raw: string
  model_id?: number | null
  model_code?: string | null
  brand_code?: string | null
  category_name?: string
  attr_count?: number
  match_source?: string
  dispute_reason?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  candidates?: MatchCandidateOut[]
  brand_identified?: number
  sales_qty?: number | null
}

type DisabledItem = {
  id: number
  item_name: string
  brand_raw: string
  match_status: string
  disable_reason: string | null
}

type ModelOption = {
  id: number
  brand_code: string
  model_code: string
  brand_name: string | null
  model_name: string | null
}

const modelOptionFromModel = (model: ModelItem): ModelOption => ({
  id: model.id,
  brand_code: model.brand_code,
  model_code: model.model_code,
  brand_name: model.brand_name ?? null,
  model_name: model.model_name ?? null,
})

type PublishJob = {
  id: number
  clean_job_id: number
  status: string
  published_count: number
  created_at: string
}

type MatchProgress = {
  status: 'idle' | 'running' | 'done' | 'error'
  total: number
  processed: number
  matched: number
  rate: number | null
  eta_seconds: number | null
  error?: string
}

type ReviewTabKey = 'text_only' | 'pending' | 'unidentified_brand' | 'disputed' | 'matched' | 'confirmed' | 'excluded' | 'filtered'

type SearchBy = 'item_name' | 'brand_raw' | 'brand_code'

const searchByLabelMap: Record<SearchBy, string> = {
  item_name: '商品名称',
  brand_raw: '原品牌',
  brand_code: '入库品牌',
}

const searchByPlaceholderMap: Record<SearchBy, string> = {
  item_name: '搜索宝贝名称',
  brand_raw: '搜索原品牌',
  brand_code: '搜索入库品牌',
}

export default function MatchPage() {
  const [searchParams] = useSearchParams()
  const [selectedJobId, setSelectedJobId] = useState<number | null>(
    searchParams.get('job_id') ? Number(searchParams.get('job_id')) : null
  )
  const [running, setRunning] = useState(false)
  const [matchProgress, setMatchProgress] = useState<MatchProgress | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportProgress, setExportProgress] = useState(0)
  const [exportError, setExportError] = useState('')
  const [exportProgressVisible, setExportProgressVisible] = useState(false)
  const exportPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [summary, setSummary] = useState<MatchSummary | null>(null)
  const [keyword, setKeyword] = useState('')
  const [inputValue, setInputValue] = useState('')
  const [searchBy, setSearchBy] = useState<SearchBy>('item_name')
  const [categoryName, setCategoryName] = useState<string | undefined>()
  const [sortBy, setSortBy] = useState<string>('default')
  const [page, setPage] = useState(1)
  const [reviewedPage, setReviewedPage] = useState(1)
  const [confirmingIds, setConfirmingIds] = useState<Set<number>>(new Set())
  const [recoveringFilteredIds, setRecoveringFilteredIds] = useState<Set<number>>(new Set())
  const [selectedModels, setSelectedModels] = useState<Record<number, number>>({})
  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([])
  const [disabledItems, setDisabledItems] = useState<DisabledItem[]>([])
  const [disabledTotal, setDisabledTotal] = useState(0)
  const [disabledPage, setDisabledPage] = useState(1)
  const [disabledLoading, setDisabledLoading] = useState(false)
  const [avgPriceThreshold, setAvgPriceThreshold] = useState(200)
  const [coefficientDrafts, setCoefficientDrafts] = useState<Record<number, number | null>>({})
  const [editedCoefficientIds, setEditedCoefficientIds] = useState<Set<number>>(new Set())
  const [savingCoefficientIds, setSavingCoefficientIds] = useState<Set<number>>(new Set())
  const [activeTab, setActiveTab] = useState<ReviewTabKey>('text_only')
  const [selectedBatchIds, setSelectedBatchIds] = useState<Set<number>>(new Set())
  const [batchConfirming, setBatchConfirming] = useState(false)
  const [batchAllPages, setBatchAllPages] = useState(false)
  const resetBatchSelection = () => {
    setSelectedBatchIds(new Set())
    setBatchAllPages(false)
  }
  const [selectedReviewId, setSelectedReviewId] = useState<number | null>(null)
  const [selectedFilteredId, setSelectedFilteredId] = useState<number | null>(null)
  const [reviewDetail, setReviewDetail] = useState<MatchReviewDetail | null>(null)
  const [filteredDetail, setFilteredDetail] = useState<FilteredItemOut | null>(null)
  const [reviewDetailLoading, setReviewDetailLoading] = useState(false)
  const [reviewReason, setReviewReason] = useState('')
  const [interventionModalOpen, setInterventionModalOpen] = useState(false)
  const [rerunningRules, setRerunningRules] = useState(false)
  const { data: jobsData, refresh: refreshJobs } = useRequest(() => listCleanJobs().then(r => r.data))
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelSearchLoading, setModelSearchLoading] = useState(false)
  const [createModelOpen, setCreateModelOpen] = useState(false)
  const [reselectOpen, setReselectOpen] = useState(false)
  const [reselectMatchId, setReselectMatchId] = useState<number | null>(null)
  const { options: categoryOptions } = useCategoryOptions()
  const preciseMatchedCount = summary?.precise_matched ?? summary?.url_matched ?? 0
  const otherAutoMatchedCount = summary ? Math.max(summary.matched - Math.max(preciseMatchedCount - (summary.url_matched ?? 0), 0), 0) : 0
  const readyCount = summary ? (summary?.url_matched ?? 0) + summary.matched + summary.confirmed : 0

  const handleModelSearch = async (keyword: string) => {
    if (!keyword.trim()) return
    setModelSearchLoading(true)
    try {
      const res = await listModels({
        keyword,
        page: 1,
        page_size: 50,
        category_code: reviewDetail?.category_code || undefined,
      }).then(r => r.data)
      setModelOptions((res.items ?? []).map(modelOptionFromModel))
    } finally {
      setModelSearchLoading(false)
    }
  }

  const handleCreatedModel = (model: ModelItem) => {
    if (!reviewDetail) return
    const option = modelOptionFromModel(model)
    setModelOptions(prev => {
      const exists = prev.some(item => item.id === model.id)
      return exists ? prev : [option, ...prev]
    })
    setSelectedModels(prev => ({ ...prev, [reviewDetail.id]: model.id }))
    setCreateModelOpen(false)
    message.success('型号已创建并选中')
  }

  const { data: pendingData, loading: pendingLoading, refresh: refreshPending } = useRequest(
    () => listPendingMatches(selectedJobId!, {
      keyword: keyword || undefined,
      search_by: searchBy,
      page,
      page_size: 20,
      status: activeTab === 'unidentified_brand' ? 'pending' : activeTab,
      ...(activeTab === 'unidentified_brand' ? { brand_identified: 0 } : {}),
      category_name: categoryName || undefined,
      sort_by: sortBy !== 'default' ? sortBy : undefined,
    }).then(r => r.data),
    {
      ready: selectedJobId != null && summary != null && summary.total > 0 && activeTab !== 'filtered',
      refreshDeps: [selectedJobId, keyword, searchBy, page, activeTab, categoryName, sortBy],
    }
  )

  const { data: filteredData, loading: filteredLoading, refresh: refreshFiltered } = useRequest(
    () => listFilteredItems({
      clean_job_id: selectedJobId!,
      keyword: keyword || undefined,
      search_by: searchBy === 'brand_code' ? 'item_name' : searchBy,
      page,
      page_size: 20,
    }).then(r => r.data),
    {
      ready: selectedJobId != null && activeTab === 'filtered',
      refreshDeps: [selectedJobId, keyword, searchBy, page, activeTab],
    }
  )

  useEffect(() => {
    if (activeTab === 'filtered') return
    const items = pendingData?.items ?? []
    if (items.length === 0) {
      setSelectedReviewId(null)
      setReviewDetail(null)
      return
    }
    if (!selectedReviewId || !items.some((item: PendingItem) => item.id === selectedReviewId)) {
      setSelectedReviewId(items[0].id)
    }
  }, [activeTab, pendingData, selectedReviewId])

  useEffect(() => {
    if (activeTab !== 'filtered') return
    const items = filteredData?.items ?? []
    if (items.length === 0) {
      setSelectedFilteredId(null)
      setFilteredDetail(null)
      return
    }
    if (!selectedFilteredId || !items.some((item: FilteredItemOut) => item.id === selectedFilteredId)) {
      setSelectedFilteredId(items[0].id)
      setFilteredDetail(items[0])
    }
  }, [activeTab, filteredData, selectedFilteredId])

  useEffect(() => {
    if (!selectedReviewId || activeTab === 'filtered') return
    setReviewDetailLoading(true)
    getMatchReviewDetail(selectedReviewId)
      .then(r => {
        setReviewDetail(r.data)
        setReviewReason(r.data.dispute_reason || r.data.review_note || '')
      })
      .finally(() => setReviewDetailLoading(false))
  }, [activeTab, selectedReviewId])

  // 跨页全选模式下翻新页：新页可选项默认全部勾中（§3.3 "翻页保留"）
  useEffect(() => {
    if (!batchAllPages) return
    if (activeTab !== 'text_only' && activeTab !== 'pending') return
    const items: PendingItem[] = pendingData?.items ?? []
    const validIds = items
      .filter(item => isCandidateValidForBatch(item).ok)
      .map(item => item.id)
    setSelectedBatchIds(new Set(validIds))
  }, [batchAllPages, activeTab, pendingData])

  const { data: reviewedData, loading: reviewedLoading, refresh: refreshReviewed } = useRequest(
    () => listReviewedMatches(selectedJobId!, {
      page: reviewedPage,
      page_size: 20,
    }).then(r => r.data),
    {
      ready: selectedJobId != null && summary != null && readyCount > 0,
      refreshDeps: [selectedJobId, reviewedPage],
      onSuccess: data => {
        setCoefficientDrafts(prev => {
          const next = { ...prev }
          data.items.forEach((item: ReviewedMatchResultOut) => {
            if (!(item.id in next)) next[item.id] = item.sales_coefficient ?? null
          })
          return next
        })
      },
    }
  )

  useEffect(() => {
    if (!summary) return
    const counts: Record<ReviewTabKey, number> = {
      text_only: summary.text_only ?? 0,
      pending: summary.pending ?? 0,
      unidentified_brand: summary.unidentified_brand ?? 0,
      disputed: summary.disputed ?? 0,
      matched: (summary.matched ?? 0) + (summary.url_matched ?? 0),
      confirmed: summary.confirmed ?? 0,
      excluded: summary.excluded ?? 0,
      filtered: filteredData?.total ?? 0,
    }
    if (counts[activeTab] === 0) {
      const nextTab = (Object.entries(counts).find(([, count]) => count > 0)?.[0] ?? 'text_only') as ReviewTabKey
      if (nextTab !== activeTab) setActiveTab(nextTab)
    }
  }, [summary, activeTab, filteredData?.total])

  // 组件卸载时清理轮询计时器，防止离开页面后仍持续请求
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    return () => {
      if (exportPollRef.current) {
        clearInterval(exportPollRef.current)
        exportPollRef.current = null
      }
    }
  }, [])

  // 选任务后自动拉取摘要 + 发布历史；若后台匹配正在运行则自动恢复轮询
  useEffect(() => {
    if (!selectedJobId) return
    getMatchSummary(selectedJobId)
      .then(r => setSummary(r.data))
      .catch(() => setSummary(null))
    listPublishJobs(selectedJobId)
      .then(r => setPublishJobs(r.data.data ?? []))
      .catch(() => setPublishJobs([]))
    loadDisabled()
    // 检查是否有正在运行的匹配任务（切走后回来时恢复进度显示）
    getMatchProgress(selectedJobId).then(res => {
      const p: MatchProgress = res.data
      if (p.status === 'running') {
        setRunning(true)
        setMatchProgress(p)
        startPolling(selectedJobId)
      }
    }).catch(() => {})
  }, [selectedJobId])

  const startPolling = (jobId: number) => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await getMatchProgress(jobId)
        const p: MatchProgress = res.data
        setMatchProgress(p)
        if (p.status === 'done') {
          clearInterval(pollTimerRef.current!)
          pollTimerRef.current = null
          setRunning(false)
          message.success(`匹配完成：已匹配 ${p.matched} 条，待确认 ${p.total - p.matched} 条`)
          getMatchSummary(jobId).then(r => setSummary(r.data))
          refreshPending()
          refreshReviewed()
        } else if (p.status === 'error') {
          clearInterval(pollTimerRef.current!)
          pollTimerRef.current = null
          setRunning(false)
          message.error(`匹配出错：${p.error}`)
        } else if (p.status === 'idle') {
          // 后端重启导致进度状态丢失，停止轮询
          clearInterval(pollTimerRef.current!)
          pollTimerRef.current = null
          setRunning(false)
          setMatchProgress(null)
        }
      } catch {
        // 网络抖动时忽略，继续轮询
      }
    }, 1500)
  }

  const handleRunMatch = async () => {
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    setRunning(true)
    setSummary(null)   // 清除旧统计，避免展示中间批次的半成品数据
    setMatchProgress({ status: 'running', total: 0, processed: 0, matched: 0, rate: null, eta_seconds: null })
    try {
      await runMatch(selectedJobId)
    } catch {
      setRunning(false)
      setMatchProgress(null)
      return
    }
    startPolling(selectedJobId)
  }

  const selectNextReview = (matchId: number) => {
    const items = pendingData?.items ?? []
    const index = items.findIndex((item: PendingItem) => item.id === matchId)
    const next = items[index + 1] ?? items[index - 1] ?? null
    setSelectedReviewId(next?.id ?? null)
    if (!next) setReviewDetail(null)
  }

  const refreshReviewWorkbench = (matchId: number) => {
    selectNextReview(matchId)
    refreshPending()
    refreshReviewed()
    getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
  }

  const refreshReviewDetailInPlace = async (matchId: number) => {
    refreshPending()
    refreshReviewed()
    if (selectedJobId) getMatchSummary(selectedJobId).then(r => setSummary(r.data))
    setReviewDetailLoading(true)
    try {
      const res = await getMatchReviewDetail(matchId)
      setReviewDetail(res.data)
      setSelectedReviewId(matchId)
      setReviewReason(res.data.dispute_reason || res.data.review_note || '')
    } finally {
      setReviewDetailLoading(false)
    }
  }

  const openReselectModal = (row: ReviewedMatchResultOut) => {
    setReselectMatchId(row.id)
    setReselectOpen(true)
  }

  const handleReselectSuccess = async (id: number) => {
    if (selectedReviewId === id && activeTab !== 'filtered') {
      await refreshReviewDetailInPlace(id)
    } else {
      refreshPending()
      refreshReviewed()
      if (selectedJobId) getMatchSummary(selectedJobId).then(r => setSummary(r.data))
    }
  }

  const refreshCurrentJobState = () => {
    if (!selectedJobId) return
    setSelectedReviewId(null)
    setSelectedFilteredId(null)
    setReviewDetail(null)
    setFilteredDetail(null)
    setReviewReason('')
    setSelectedModels({})
    setPage(1)
    setReviewedPage(1)
    refreshJobs()
    getMatchSummary(selectedJobId).then(r => setSummary(r.data))
    refreshPending()
    refreshReviewed()
    loadDisabled()
  }

  const handleRerunWithCurrentRules = async () => {
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    Modal.confirm({
      title: '应用规则并重新处理当前任务？',
      content: '将使用最新干预规则重新处理当前任务。已沉淀 URL 映射的人工确认结果会自动复用，系统也会按原始行恢复本任务内已确认和已排除的人工审核结果。被新规则过滤的数据将进入干扰项存档，不会发布。',
      onOk: async () => {
        setRerunningRules(true)
        try {
          const res = await rerunCleanTaskWithCurrentRules(selectedJobId)
          const restoredReviewCount = res.data.restored_review_count ?? res.data.restored_confirmed_count
          message.success(`重新处理完成：清洗后 ${res.data.row_out} 条，过滤 ${res.data.filtered_count} 条，恢复人工审核 ${restoredReviewCount} 条`)
          refreshCurrentJobState()
        } finally {
          setRerunningRules(false)
        }
      },
    })
  }

  const handleBatchConfirm = async () => {
    if (!selectedJobId) return
    const useFilterMode = batchAllPages
    const filter: BatchConfirmFilter = {
      tab: activeTab as 'text_only' | 'pending',
      keyword: keyword || null,
      search_by: searchBy,
      category_name: categoryName ?? null,
      sort_by: sortBy as BatchConfirmFilter['sort_by'],
    }
    let title = ''
    let distributionLines: string[] = []
    let processCount = 0
    let truncatedNote = ''

    if (useFilterMode) {
      let preview
      try {
        const resp = await previewBatchConfirmMatch(selectedJobId, filter)
        preview = resp.data
      } catch (err: any) {
        message.error(err?.response?.data?.detail || '预览候选分布失败')
        return
      }
      if (preview.total_valid === 0) {
        message.info('没有可确认的有效候选')
        return
      }
      processCount = preview.total_valid
      if (preview.total_valid > 500) {
        truncatedNote = `\n※ 超出单次上限，将只处理前 500 条，剩余 ${preview.total_valid - 500} 条请再次执行。`
        processCount = 500
      }
      distributionLines = preview.candidate_distribution.map(d =>
        `  · [${d.brand_code}] ${d.model_code} × ${d.count}`,
      )
      title = `将确认 ${processCount} 条为系统候选型号`
    } else {
      if (selectedBatchIds.size === 0) return
      processCount = selectedBatchIds.size
      // 本地聚合展示
      const items = pendingData?.items ?? []
      const dist = new Map<string, number>()
      items.filter((i: PendingItem) => selectedBatchIds.has(i.id)).forEach((i: PendingItem) => {
        const top = getTopCandidate(i)
        if (!top) return
        const k = `[${top.brand_code}] ${top.model_code}`
        dist.set(k, (dist.get(k) ?? 0) + 1)
      })
      distributionLines = Array.from(dist.entries()).map(([k, v]) => `  · ${k} × ${v}`)
      title = `将确认 ${processCount} 条为系统候选型号`
    }

    Modal.confirm({
      title,
      width: 480,
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          <div>候选型号分布：</div>
          <div>{distributionLines.join('\n') || '  · （无）'}</div>
          {truncatedNote && <div style={{ color: '#d48806' }}>{truncatedNote}</div>}
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        setBatchConfirming(true)
        try {
          const { data } = useFilterMode
            ? await batchConfirmMatch(selectedJobId, { mode: 'filter', filter })
            : await batchConfirmMatch(selectedJobId, { mode: 'ids', ids: Array.from(selectedBatchIds) })
          showBatchResult(data)
          refreshPending()
          if (selectedJobId) getMatchSummary(selectedJobId).then(r => setSummary(r.data))
        } catch (err: any) {
          message.error(err?.response?.data?.detail || '批量确认失败')
        } finally {
          setBatchConfirming(false)
        }
      },
    })
  }

  const showBatchResult = (data: BatchConfirmResult) => {
    if (data.failed === 0) {
      message.success(`已确认 ${data.success} 条`)
      resetBatchSelection()
      return
    }
    const failedIds = new Set(data.failures.map(f => f.id))
    const nextSelected = new Set<number>()
    failedIds.forEach(id => nextSelected.add(id))  // 失败条目保持勾选
    setSelectedBatchIds(nextSelected)
    setBatchAllPages(false)
    Modal.info({
      title: `成功 ${data.success} 条，失败 ${data.failed} 条`,
      width: 640,
      content: (
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={data.failures}
          scroll={{ y: 320 }}
          columns={[
            { title: '商品', dataIndex: 'item_name', ellipsis: true },
            { title: '失败原因', dataIndex: 'reason', width: 220 },
          ]}
        />
      ),
      okText: '知道了',
    })
  }

  const handleExclude = async (matchId: number) => {
    const reason = reviewReason.trim()
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await confirmMatch(matchId, { excluded: true, reason: reason || undefined })
      message.success('已排除')
      refreshReviewWorkbench(matchId)
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handleRevert = async (matchId: number) => {
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await revertMatch(matchId)
      message.success('已撤销，恢复到操作前状态')
      refreshReviewWorkbench(matchId)
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handleSelectCandidate = async (matchId: number, modelId: number) => {
    await confirmMatch(matchId, { model_id: modelId })
    message.success('已选用候选型号，右侧已刷新确认结果')
    await refreshReviewDetailInPlace(matchId)
  }

  const handleSelectOtherModel = async (matchId: number, modelId: number) => {
    setSelectedModels(prev => ({ ...prev, [matchId]: modelId }))
    await confirmMatch(matchId, { model_id: modelId })
    message.success('已选择其他型号，右侧已刷新确认结果')
    await refreshReviewDetailInPlace(matchId)
  }

  const handleRecoverFilteredItem = async (item: FilteredItemOut) => {
    setRecoveringFilteredIds(prev => new Set(prev).add(item.id))
    try {
      await recoverFilteredItem(item.id)
      message.success('已恢复到清洗结果，重新匹配后可进入复核队列')
      setSelectedFilteredId(null)
      setFilteredDetail(null)
      refreshFiltered()
      refreshJobs()
      if (selectedJobId) getMatchSummary(selectedJobId).then(r => setSummary(r.data))
    } finally {
      setRecoveringFilteredIds(prev => { const s = new Set(prev); s.delete(item.id); return s })
    }
  }

  const handleSaveCoefficient = async (matchId: number) => {
    const coefficient = coefficientDrafts[matchId] ?? null
    setSavingCoefficientIds(prev => new Set(prev).add(matchId))
    try {
      const res = await updateMatchCoefficient(matchId, coefficient)
      setCoefficientDrafts(prev => ({ ...prev, [matchId]: res.data.sales_coefficient ?? null }))
      setEditedCoefficientIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
      message.success(coefficient == null ? '已清除调整系数' : '已保存调整系数')
      refreshReviewed()
    } finally {
      setSavingCoefficientIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handlePublish = async () => {
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    if (!summary || (summary.url_matched ?? 0) + summary.matched + summary.confirmed === 0) {
      message.warning('没有可发布的已匹配数据')
      return
    }
    setPublishing(true)
    try {
      if (selectedJob?.category_code && selectedJob.platform && selectedJob.month) {
        try {
          const poolSummary = await getCleanMonthlyPool({
            category_code: selectedJob.category_code,
            platform: selectedJob.platform,
            month: selectedJob.month,
          }).then(r => r.data)
          const pendingInScope = poolSummary.reduce((sum, item) => sum + item.pending_count, 0)
          if (pendingInScope > 0) {
            message.info(`该任务范围还有 ${pendingInScope} 条数据未进入清洗任务，本次发布不会包含这些数据。`, 6)
          }
        } catch (error) {
          console.warn('Failed to load monthly clean pool before publishing', error)
        }
      }
      const res = await runPublish(selectedJobId)
      const { published_count, skipped_pending_count } = res.data.data
      message.success(`发布成功，共写入 ${published_count} 条到分析库`)
      const blockedCount = skipped_pending_count + (summary?.text_only ?? 0) + (summary?.disputed ?? 0)
      if (blockedCount > 0) {
        message.warning(
          `另有 ${skipped_pending_count} 条待确认、${summary?.text_only ?? 0} 条URL映射待确认、${summary?.disputed ?? 0} 条争议未发布`,
          6,
        )
      }
      // 刷新发布历史
      listPublishJobs(selectedJobId).then(r => setPublishJobs(r.data.data ?? []))
    } finally {
      setPublishing(false)
    }
  }

  const stopExportPoll = () => {
    if (exportPollRef.current) {
      clearInterval(exportPollRef.current)
      exportPollRef.current = null
    }
  }

  const handleExport = async () => {
    if (exportPollRef.current) return
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    setExporting(true)
    setExportProgress(0)
    setExportError('')
    setExportProgressVisible(true)
    try {
      const res = await triggerExport({ clean_job_id: selectedJobId, filename_prefix: '匹配结果' })
      const { job_id: jobId } = res.data as { job_id: number }

      let pollFailCount = 0
      exportPollRef.current = setInterval(async () => {
        try {
          const jobRes = await getExportJob(jobId)
          const job = jobRes.data as {
            status: string; token?: string | null; error_msg?: string | null; rows?: number
          }
          pollFailCount = 0
          if (job.status === 'running') setExportProgress(50)
          if (job.status === 'done' && job.token) {
            stopExportPoll()
            setExportProgress(100)
            setTimeout(() => {
              setExportProgressVisible(false)
              setExporting(false)
              const a = document.createElement('a')
              a.href = getDownloadUrl(job.token!)
              a.click()
            }, 800)
          } else if (job.status === 'error') {
            stopExportPoll()
            setExportError(job.error_msg || '导出失败，请重试')
            setExporting(false)
          }
        } catch {
          pollFailCount++
          if (pollFailCount >= 10) {
            stopExportPoll()
            setExportError('网络异常，请刷新后重试')
            setExporting(false)
          }
        }
      }, 1000)
    } catch {
      setExportProgressVisible(false)
      setExporting(false)
    }
  }

  const loadDisabled = async (page = 1) => {
    if (!selectedJobId) return
    setDisabledLoading(true)
    try {
      const res = await listDisabled(selectedJobId, page)
      setDisabledItems(res.data.items ?? [])
      setDisabledTotal(res.data.total)
      setDisabledPage(page)
    } finally {
      setDisabledLoading(false)
    }
  }

  const reviewedColumns = [
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string | null) => v ? <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip> : '-'
    },
    { title: '品牌', dataIndex: 'brand_raw', width: 110, render: (v: string | null) => v ?? '-' },
    {
      title: '匹配型号', width: 160,
      render: (_: unknown, row: ReviewedMatchResultOut) =>
        hasDisplayModel(row.brand_code, row.model_code)
          ? <Text code style={{ fontSize: 12 }}>[{row.brand_code}] {row.model_code}</Text>
          : <Text type="secondary">-</Text>
    },
    {
      title: '价格预警', width: 110,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const flag = row.price_flag
        if (!flag) return <Tag color="default">-</Tag>
        const meta = priceFlagMeta[flag]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '参考均价', dataIndex: 'price_ref', width: 100,
      render: (v: number | null) => v != null ? `¥${v.toLocaleString()}` : '-'
    },
    {
      title: '原销量', dataIndex: 'sales_qty', width: 90,
      render: (v: number | null) => formatNumber(v),
    },
    {
      title: '修正销量', dataIndex: 'corrected_sales_qty', width: 90,
      render: (_: number | null, row: ReviewedMatchResultOut) => formatNumber(getBaseSalesQty(row)),
    },
    {
      title: '调整系数', width: 180,
      render: (_: unknown, row: ReviewedMatchResultOut) => (
        <Space size={4}>
          <InputNumber
            size="small"
            min={0}
            max={999.9999}
            precision={4}
            placeholder="不调整"
            value={coefficientDrafts[row.id] ?? null}
            onChange={v => {
              setCoefficientDrafts(prev => ({ ...prev, [row.id]: v == null ? null : Number(v) }))
              setEditedCoefficientIds(prev => new Set(prev).add(row.id))
            }}
            style={{ width: 100 }}
          />
          <Button
            size="small"
            loading={savingCoefficientIds.has(row.id)}
            onClick={() => handleSaveCoefficient(row.id)}
          >保存</Button>
        </Space>
      ),
    },
    {
      title: '调整后销量', width: 100,
      render: (_: unknown, row: ReviewedMatchResultOut) => formatNumber(
        getAdjustedSalesQty(row, coefficientDrafts[row.id], editedCoefficientIds.has(row.id))
      ),
    },
    {
      title: '状态', dataIndex: 'match_status', width: 90,
      render: (v: string) => <Tag color={v === 'confirmed' ? 'blue' : 'green'}>{v}</Tag>,
    },
    {
      title: '来源', width: 130,
      render: (_: unknown, row: ReviewedMatchResultOut) => renderMatchSource(row.match_source),
    },
  ]

  const publishColumns = [
    { title: '发布ID', dataIndex: 'id', width: 70 },
    { title: '写入条数', dataIndex: 'published_count', width: 90 },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v: string) => <Tag color={v === 'done' ? 'green' : 'red'}>{v}</Tag>
    },
    {
      title: '发布时间', dataIndex: 'created_at',
      render: (v: string) => v || '-'
    },
  ]

  const queueTabs: Array<{ key: ReviewTabKey; label: string; count: number; color: string }> = [
    { key: 'unidentified_brand', label: '未识别品牌', count: summary?.unidentified_brand ?? 0, color: '#722ed1' },
    { key: 'text_only', label: 'URL映射待确认', count: summary?.text_only ?? 0, color: '#d48806' },
    { key: 'pending', label: '待确认', count: summary?.pending ?? 0, color: '#d46b08' },
    { key: 'disputed', label: '争议复核', count: summary?.disputed ?? 0, color: '#cf1322' },
    { key: 'matched', label: '已匹配', count: (summary?.matched ?? 0) + (summary?.url_matched ?? 0), color: '#389e0d' },
    { key: 'confirmed', label: '已人工确认', count: summary?.confirmed ?? 0, color: '#1677ff' },
    { key: 'excluded', label: '已排除', count: summary?.excluded ?? 0, color: '#8c8c8c' },
    { key: 'filtered', label: '干扰项过滤', count: filteredData?.total ?? 0, color: '#fa8c16' },
  ]

  const currentQueueTitle = queueTabs.find(tab => tab.key === activeTab)?.label ?? '复核'
  const selectedJob = (jobsData ?? []).find((job: CleanJobItem) => job.id === selectedJobId)
  const cleanJobs = jobsData ?? []
  const canRetryMatch = selectedJob?.status === 'failed' || selectedJob?.status === 'error'
  const metadataPendingCount = summary
    ? (summary.pending ?? 0) + (summary.text_only ?? 0) + (summary.disputed ?? 0)
    : selectedJob?.pending_count ?? 0
  const metadataPublishableCount = summary ? readyCount : selectedJob?.publishable_count ?? 0

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="清洗任务详情">
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>当前清洗任务：</Text>
          </Col>
          <Col flex="200px">
            <Select
              style={{ width: '100%' }}
              placeholder="选择任务"
              value={selectedJobId}
              onChange={v => { setSelectedJobId(v); setSummary(null); setPage(1); setReviewedPage(1); setPublishJobs([]); setCoefficientDrafts({}); setEditedCoefficientIds(new Set()); resetBatchSelection() }}
              options={cleanJobs.map((j: CleanJobItem) => ({
                value: j.id,
                label: `${j.task_name || j.scope_desc || `任务#${j.id}`}｜${j.row_out}条｜${j.created_at?.slice(0, 10) || '-'}`,
              }))}
            />
          </Col>
          {canRetryMatch && (
            <Col>
              <Button
                type="primary"
                icon={<AimOutlined />}
                loading={running}
                onClick={handleRunMatch}
                disabled={!selectedJobId}
              >
                重新匹配
              </Button>
            </Col>
          )}
          <Col>
            <Button
              icon={<CloudUploadOutlined />}
              loading={publishing}
              onClick={handlePublish}
              disabled={!selectedJobId || readyCount === 0}
              style={{ borderColor: '#52c41a', color: '#52c41a' }}
            >
              发布到分析库
            </Button>
          </Col>
          <Col>
            <Button
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={handleExport}
              disabled={!selectedJobId}
            >
              导出
            </Button>
          </Col>
        </Row>
      </Card>

      {selectedJob && (
        <Card size="small">
          <Descriptions column={4} size="small" bordered>
            <Descriptions.Item label="任务名称">
              {selectedJob.task_name || selectedJob.scope_desc || `任务 #${selectedJob.id}`}
            </Descriptions.Item>
            <Descriptions.Item label="品类">
              {selectedJob.category_code || selectedJob.dispatch_category_code || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="平台">
              {selectedJob.platform || '全部'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag>{selectedJob.status || '-'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="原始行数">
              {formatNumber(selectedJob.row_in)}
            </Descriptions.Item>
            <Descriptions.Item label="清洗后">
              {formatNumber(selectedJob.row_out)}
            </Descriptions.Item>
            <Descriptions.Item label="待处理">
              {formatNumber(metadataPendingCount)}
            </Descriptions.Item>
            <Descriptions.Item label="可发布">
              {formatNumber(metadataPublishableCount)}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {selectedJobId && summary && summary.total > 0 && (
        <Card size="small">
          <Space wrap>
            <Text>均价批量禁用：</Text>
            <InputNumber
              value={avgPriceThreshold}
              onChange={v => setAvgPriceThreshold(v ?? 200)}
              addonBefore="价格低于"
              addonAfter="元"
              min={0}
              style={{ width: 200 }}
            />
            <Popconfirm
              title={`将禁用价格低于 ${avgPriceThreshold} 元的已匹配数据，是否继续？`}
              onConfirm={async () => {
                if (!selectedJobId) return
                const res = await avgPriceDisable(selectedJobId, avgPriceThreshold)
                message.success(`均价禁用完成，共禁用 ${res.data.disabled_count} 条`)
                getMatchSummary(selectedJobId).then(r => setSummary(r.data))
                refreshReviewed()
                loadDisabled()
              }}
            >
              <Button>均价批量禁用</Button>
            </Popconfirm>
          </Space>
        </Card>
      )}

      {matchProgress && matchProgress.status === 'running' && (
        <Card>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Row justify="space-between" align="middle">
              <Col>
                <Space>
                  <LoadingOutlined style={{ color: '#1677ff' }} />
                  <Text strong>正在匹配…</Text>
                  {matchProgress.total > 0 && (
                    <Text type="secondary">
                      {matchProgress.processed.toLocaleString()} / {matchProgress.total.toLocaleString()} 条
                    </Text>
                  )}
                </Space>
              </Col>
              <Col>
                <Space size={16}>
                  {matchProgress.rate != null && (
                    <Text type="secondary">速度 {matchProgress.rate} 条/秒</Text>
                  )}
                  {matchProgress.eta_seconds != null && matchProgress.eta_seconds > 0 && (
                    <Text type="secondary">
                      预计还需 {matchProgress.eta_seconds >= 60
                        ? `${Math.floor(matchProgress.eta_seconds / 60)} 分 ${matchProgress.eta_seconds % 60} 秒`
                        : `${matchProgress.eta_seconds} 秒`}
                    </Text>
                  )}
                  {matchProgress.matched > 0 && (
                    <Text style={{ color: '#3f8600' }}>已匹配 {matchProgress.matched.toLocaleString()} 条</Text>
                  )}
                </Space>
              </Col>
            </Row>
            <Progress
              percent={matchProgress.total > 0 ? Math.round(matchProgress.processed / matchProgress.total * 100) : 0}
              status="active"
              strokeColor={{ from: '#1677ff', to: '#52c41a' }}
            />
          </Space>
        </Card>
      )}

      {matchProgress && matchProgress.status === 'error' && (
        <Alert type="error" message={`匹配出错：${matchProgress.error}`} showIcon />
      )}

      {summary && summary.total > 0 && (
        <Card>
          <Row gutter={16}>
            <Col span={3}><Statistic title="总条数" value={summary.total} /></Col>
            <Col span={3}><Statistic title="精准匹配" value={preciseMatchedCount} valueStyle={{ color: '#389e0d' }} /></Col>
            <Col span={3}><Statistic title="其他自动匹配" value={otherAutoMatchedCount} valueStyle={{ color: '#3f8600' }} /></Col>
            <Col span={3}><Statistic title="URL映射待确认" value={summary.text_only ?? 0} valueStyle={{ color: '#d48806' }} /></Col>
            <Col span={3}><Statistic title="待确认" value={summary.pending} valueStyle={{ color: '#d46b08' }} /></Col>
            <Col span={3}><Statistic title="已人工确认" value={summary.confirmed} valueStyle={{ color: '#1677ff' }} /></Col>
            <Col span={2}><Statistic title="已排除" value={summary.excluded} valueStyle={{ color: '#cf1322' }} /></Col>
            <Col span={2}><Statistic title="已禁用" value={summary.disabled ?? 0} valueStyle={{ color: '#faad14' }} /></Col>
            <Col span={3}>
              <Statistic
                title="未识别品牌"
                value={summary?.unidentified_brand ?? 0}
                valueStyle={{ color: '#722ed1' }}
              />
            </Col>
            <Col span={3}>
              <Statistic
                title="匹配率"
                value={summary.total ? Math.round(
                  ((summary.url_matched ?? 0) + summary.matched + summary.confirmed) / summary.total * 100
                ) : 0}
                suffix="%"
                valueStyle={{ color: '#3f8600' }}
              />
            </Col>
          </Row>
        </Card>
      )}

      {summary && summary.total > 0 && (
        <Card
          title={
            <Space>
              <span>任务复核工作台</span>
              <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                待处理 {(summary.text_only ?? 0) + summary.pending + (summary.disputed ?? 0)} 条 · 已匹配/确认 {readyCount} 条 · 已排除 {summary.excluded ?? 0} 条 · 干扰过滤 {filteredData?.total ?? 0} 条
              </span>
            </Space>
          }
          extra={
            <Space>
              <Button
                size="small"
                onClick={() => setInterventionModalOpen(true)}
                disabled={!selectedJob?.category_code && !selectedJob?.dispatch_category_code}
              >
                干扰项规则
              </Button>
              <Button
                size="small"
                loading={rerunningRules}
                onClick={handleRerunWithCurrentRules}
                disabled={!selectedJobId}
              >
                应用规则并重新处理当前任务
              </Button>
              <Select
                placeholder="品类筛选"
                allowClear
                style={{ width: 140 }}
                options={categoryOptions}
                onChange={v => { setCategoryName(v); setPage(1); resetBatchSelection() }}
              />
              <Select
                value={sortBy}
                style={{ width: 130 }}
                onChange={v => { setSortBy(v); setPage(1); resetBatchSelection() }}
                options={[
                  { value: 'default', label: '默认排序' },
                  { value: 'sales_qty_desc', label: '销量从高到低' },
                  { value: 'sales_qty_asc', label: '销量从低到高' },
                ]}
              />
              <Select
                value={searchBy}
                onChange={next => {
                  setSearchBy(next)
                  setKeyword('')
                  setInputValue('')
                  setPage(1)
                  resetBatchSelection()
                }}
                style={{ width: 130 }}
                options={(activeTab === 'filtered'
                  ? (['item_name', 'brand_raw'] as SearchBy[])
                  : (['item_name', 'brand_raw', 'brand_code'] as SearchBy[])
                ).map(value => ({ value, label: searchByLabelMap[value] }))}
              />
              <Input.Search
                placeholder={searchByPlaceholderMap[searchBy]}
                allowClear
                style={{ width: 180 }}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onSearch={v => { setInputValue(v); setKeyword(v); setPage(1); resetBatchSelection() }}
              />
            </Space>
          }
        >
          <Tabs
            activeKey={activeTab}
            onChange={key => {
              const nextTab = key as ReviewTabKey
              setActiveTab(nextTab)
              setPage(1)
              setKeyword('')
              setInputValue('')
              setCategoryName(undefined)
              setSortBy('default')
              setSelectedReviewId(null)
              setSelectedFilteredId(null)
              setReviewDetail(null)
              setFilteredDetail(null)
              setReviewReason('')
              resetBatchSelection()
              if (nextTab === 'filtered' && searchBy === 'brand_code') {
                setSearchBy('item_name')
              }
            }}
            items={queueTabs.map(tab => ({
              key: tab.key,
              label: (
                <span>
                  {tab.label}
                  {tab.count > 0 && (
                    <span style={{
                      marginLeft: 6, background: tab.color, color: '#fff',
                      borderRadius: 10, padding: '0 6px', fontSize: 11,
                    }}>
                      {tab.count}
                    </span>
                  )}
                </span>
              ),
              children: null,
            }))}
          />
          {(activeTab === 'text_only' || activeTab === 'pending') && (() => {
            const items: PendingItem[] = pendingData?.items ?? []
            const validIds = items.filter((item: PendingItem) => isCandidateValidForBatch(item).ok).map((item: PendingItem) => item.id)
            const selectedOnPage = validIds.filter((id: number) => selectedBatchIds.has(id))
            const allChecked = validIds.length > 0 && selectedOnPage.length === validIds.length
            const someChecked = selectedOnPage.length > 0 && !allChecked
            const toggleAll = (checked: boolean) => {
              const next = new Set(selectedBatchIds)
              if (checked) validIds.forEach((id: number) => next.add(id))
              else validIds.forEach((id: number) => next.delete(id))
              setSelectedBatchIds(next)
            }
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: '#fafafa', border: '1px solid #f0f0f0', marginBottom: 12 }}>
                <Checkbox
                  checked={allChecked}
                  indeterminate={someChecked}
                  disabled={validIds.length === 0}
                  onChange={e => toggleAll(e.target.checked)}
                >
                  全选当前页（{validIds.length}）
                </Checkbox>
                <span style={{ color: '#8c8c8c', fontSize: 12 }}>已选 {selectedBatchIds.size} 条</span>
                <div style={{ flex: 1 }} />
                <Button
                  type="primary"
                  loading={batchConfirming}
                  disabled={selectedBatchIds.size === 0}
                  onClick={() => handleBatchConfirm()}
                >
                  一键确认（{selectedBatchIds.size}）
                </Button>
              </div>
            )
          })()}
          {(activeTab === 'text_only' || activeTab === 'pending') && pendingData && (() => {
            const items: PendingItem[] = pendingData.items ?? []
            const validIdsOnPage = items.filter((item: PendingItem) => isCandidateValidForBatch(item).ok).map((item: PendingItem) => item.id)
            const allPageChecked = validIdsOnPage.length > 0 && validIdsOnPage.every((id: number) => selectedBatchIds.has(id))
            const hasMorePages = pendingData.total > items.length
            if (!allPageChecked || !hasMorePages) return null
            return (
              <div style={{ padding: '6px 12px', background: '#fffbe6', border: '1px solid #ffe58f', marginBottom: 12, fontSize: 13 }}>
                {batchAllPages ? (
                  <>已选中全部 <b>{pendingData.total}</b> 条搜索结果（含跨页） <Button type="link" size="small" onClick={() => setBatchAllPages(false)}>取消跨页选择</Button></>
                ) : (
                  <>已选中当前页 {validIdsOnPage.length} 条 · <Button type="link" size="small" onClick={() => setBatchAllPages(true)}>选择全部搜索结果的 {pendingData.total} 条</Button></>
                )}
              </div>
            )
          })()}
          {activeTab === 'unidentified_brand' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                <span>
                  以下商品的品牌在系统中未能识别，建议先前往「规则管理 → 品牌写法库」补充写法后重新匹配，效率高于逐条人工确认。
                  <Button type="link" size="small" onClick={() => window.open('/rules', '_blank')}>前往规则管理 →</Button>
                </span>
              }
            />
          )}
          <Row gutter={16} align="top">
            <Col span={9}>
              <Card
                size="small"
                title={`${currentQueueTitle}队列`}
                bodyStyle={{
                  padding: 0,
                  height: 'calc(100vh - 220px)',
                  minHeight: 480,
                  overflowY: 'auto',
                }}
              >
                {activeTab === 'filtered' ? (
                  <List
                    loading={filteredLoading}
                    dataSource={filteredData?.items ?? []}
                    locale={{ emptyText: '当前暂无干扰项过滤记录' }}
                    pagination={{
                      current: page,
                      pageSize: 20,
                      total: filteredData?.total ?? 0,
                      onChange: setPage,
                      size: 'small',
                      showSizeChanger: false,
                    }}
                    renderItem={(item: FilteredItemOut) => (
                      <List.Item
                        onClick={() => { setSelectedFilteredId(item.id); setFilteredDetail(item) }}
                        style={{
                          cursor: 'pointer',
                          padding: '10px 12px',
                          background: selectedFilteredId === item.id ? '#fff7e6' : undefined,
                        }}
                      >
                        <List.Item.Meta
                          title={
                            <Tooltip title={item.item_name}>
                              <Text strong ellipsis style={{ maxWidth: 280 }}>{item.item_name || '-'}</Text>
                            </Tooltip>
                          }
                          description={
                            <Space direction="vertical" size={4} style={{ width: '100%' }}>
                              <Space wrap size={4}>
                                <Tag color="orange">干扰过滤</Tag>
                                <Tag color="blue">{item.brand_raw || '无原品牌'}</Tag>
                                {item.item_url && <Tag icon={<LinkOutlined />} color="green">有链接</Tag>}
                              </Space>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                规则 {item.intervention_rule_name || '-'} · 关键词 {item.matched_keyword || '-'}
                              </Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                ) : (
                  <List
                    loading={pendingLoading}
                    dataSource={pendingData?.items ?? []}
                    locale={{ emptyText: '当前队列暂无数据' }}
                    pagination={{
                      current: page,
                      pageSize: 20,
                      total: pendingData?.total ?? 0,
                      onChange: (p: number) => { setPage(p) },
                      size: 'small',
                      showSizeChanger: false,
                    }}
                    renderItem={(item: PendingItem) => {
                      const showCheckbox = activeTab === 'text_only' || activeTab === 'pending'
                      const candValidation = isCandidateValidForBatch(item)
                      const checked = selectedBatchIds.has(item.id)
                      return (
                        <List.Item
                          onClick={() => setSelectedReviewId(item.id)}
                          style={{
                            cursor: 'pointer',
                            padding: '10px 12px',
                            background: selectedReviewId === item.id ? '#e6f4ff' : undefined,
                          }}
                        >
                          {showCheckbox && (
                            <Tooltip title={candValidation.ok ? '' : candValidation.reason}>
                              <Checkbox
                                style={{ marginRight: 8, marginTop: 4, alignSelf: 'flex-start' }}
                                disabled={!candValidation.ok}
                                checked={checked}
                                onClick={e => e.stopPropagation()}
                                onChange={e => {
                                  const next = new Set(selectedBatchIds)
                                  if (e.target.checked) next.add(item.id)
                                  else next.delete(item.id)
                                  setSelectedBatchIds(next)
                                }}
                              />
                            </Tooltip>
                          )}
                          <List.Item.Meta
                            title={
                              <Tooltip title={item.item_name}>
                                <Text strong ellipsis style={{ maxWidth: 280 }}>{item.item_name || '-'}</Text>
                              </Tooltip>
                            }
                            description={
                              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                                <Space wrap size={4}>
                                  <Tag>{item.category_name || '未归类'}</Tag>
                                  <Tag color="blue">{item.brand_raw || '无原品牌'}</Tag>
                                  {renderMatchSource(item.match_source)}
                                  {item.item_url && <Tag icon={<LinkOutlined />} color="green">有链接</Tag>}
                                </Space>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  销量 {formatNumber(item.sales_qty)}{item.dispute_reason ? ` · ${item.dispute_reason}` : ''}
                                </Text>
                              </Space>
                            }
                          />
                        </List.Item>
                      )
                    }}
                  />
                )}
              </Card>
            </Col>
            <Col span={15}>
              <Card
                size="small"
                title={activeTab === 'filtered' ? '干扰项详情' : '详情处理'}
                loading={activeTab === 'filtered' ? filteredLoading : reviewDetailLoading}
                bodyStyle={{
                  height: 'calc(100vh - 220px)',
                  minHeight: 480,
                  overflowY: 'auto',
                }}
                extra={activeTab === 'filtered'
                  ? (filteredDetail ? (
                    <Space>
                      <Tag color="orange">干扰过滤</Tag>
                      {filteredDetail.item_url ? <a href={filteredDetail.item_url} target="_blank" rel="noreferrer"><LinkOutlined /> 打开商品</a> : null}
                    </Space>
                  ) : null)
                  : (reviewDetail ? (
                    <Space>
                      <Button
                        size="small"
                        danger
                        icon={<StopOutlined />}
                        loading={confirmingIds.has(reviewDetail.id)}
                        onClick={() => handleExclude(reviewDetail.id)}
                      >排除</Button>
                      {reviewDetail.revertible ? (
                        <Popconfirm
                          title="撤销此条操作？"
                          description="将回到操作前的状态；已同步到 URL 映射库的确认记录不会自动回滚。"
                          okText="撤销"
                          cancelText="取消"
                          onConfirm={() => handleRevert(reviewDetail.id)}
                        >
                          <Button
                            size="small"
                            icon={<UndoOutlined />}
                            loading={confirmingIds.has(reviewDetail.id)}
                          >撤销</Button>
                        </Popconfirm>
                      ) : null}
                      {renderMatchStatus(reviewDetail.match_status)}
                      <Button size="small" onClick={() => refreshReviewWorkbench(reviewDetail.id)}>继续下一条</Button>
                      {reviewDetail.item_url ? <a href={reviewDetail.item_url} target="_blank" rel="noreferrer"><LinkOutlined /> 打开商品</a> : null}
                      {reviewDetail.item_image ? (
                        <Image
                          src={reviewDetail.item_image}
                          alt="商品图片"
                          width={28}
                          height={28}
                          style={{ objectFit: 'cover', borderRadius: 4 }}
                          preview={{ mask: false }}
                        />
                      ) : null}
                    </Space>
                  ) : null)}
              >
                {activeTab === 'filtered' ? (
                  !filteredDetail ? (
                    <Empty description="请选择左侧干扰项记录" />
                  ) : (
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      <Descriptions size="small" column={2} bordered>
                        <Descriptions.Item label="商品名称" span={2}>{filteredDetail.item_name || '-'}</Descriptions.Item>
                        <Descriptions.Item label="原品牌">{filteredDetail.brand_raw || '-'}</Descriptions.Item>
                        <Descriptions.Item label="店铺">{filteredDetail.shop_name || '-'}</Descriptions.Item>
                        <Descriptions.Item label="平台">{filteredDetail.platform || '-'}</Descriptions.Item>
                        <Descriptions.Item label="商品ID">{filteredDetail.item_id || '-'}</Descriptions.Item>
                        <Descriptions.Item label="价格">{filteredDetail.price != null ? `¥${filteredDetail.price}` : '-'}</Descriptions.Item>
                        <Descriptions.Item label="销量">{formatNumber(filteredDetail.sales_qty)}</Descriptions.Item>
                        <Descriptions.Item label="销售额">{filteredDetail.sales_amount != null ? `¥${formatNumber(filteredDetail.sales_amount)}` : '-'}</Descriptions.Item>
                        <Descriptions.Item label="过滤时间">{filteredDetail.created_at || '-'}</Descriptions.Item>
                        <Descriptions.Item label="命中规则">{filteredDetail.intervention_rule_name || '-'}</Descriptions.Item>
                        <Descriptions.Item label="命中关键词">{filteredDetail.matched_keyword || '-'}</Descriptions.Item>
                        <Descriptions.Item label="过滤原因" span={2}>{filteredDetail.matched_reason || '-'}</Descriptions.Item>
                      </Descriptions>

                      <Alert
                        type="warning"
                        showIcon
                        message="恢复后会回到清洗结果中，不会自动发布；如需进入复核队列，请重新匹配或重新处理当前任务。"
                      />

                      <Space wrap>
                        <Popconfirm
                          title="确认恢复此干扰项？"
                          description="恢复后该商品会重新进入清洗结果，不再作为干扰项存档排除。"
                          onConfirm={() => handleRecoverFilteredItem(filteredDetail)}
                        >
                          <Button
                            type="primary"
                            loading={recoveringFilteredIds.has(filteredDetail.id)}
                          >恢复/放行</Button>
                        </Popconfirm>
                        {filteredDetail.item_url ? <Button onClick={() => window.open(filteredDetail.item_url!, '_blank')}>打开商品链接</Button> : null}
                      </Space>
                    </Space>
                  )
                ) : !reviewDetail ? (
                  <Empty description="请选择左侧复核商品" />
                ) : (
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Descriptions size="small" column={2} bordered>
                      <Descriptions.Item label="商品名称" span={2}>{reviewDetail.item_name || '-'}</Descriptions.Item>
                      <Descriptions.Item label="原品牌">{reviewDetail.brand_raw || '-'}</Descriptions.Item>
                      <Descriptions.Item label="店铺">{reviewDetail.shop_name || '-'}</Descriptions.Item>
                      <Descriptions.Item label="入库品牌">{reviewDetail.brand_code || reviewDetail.brand_raw || '-'}</Descriptions.Item>
                      <Descriptions.Item label="当前型号">
                        <Space wrap>
                          {hasDisplayModel(reviewDetail.brand_code, reviewDetail.model_code)
                            ? <Text code>[{reviewDetail.brand_code}] {reviewDetail.model_code}</Text>
                            : <Text type="secondary">-</Text>}
                          <Select
                            showSearch
                            placeholder="搜索/选择其他型号确认"
                            style={{ minWidth: 220 }}
                            allowClear
                            filterOption={false}
                            onSearch={handleModelSearch}
                            loading={modelSearchLoading}
                            options={modelOptions.map(m => ({
                              value: m.id,
                              label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
                            }))}
                            value={selectedModels[reviewDetail.id]}
                            onChange={v => {
                              if (v) {
                                handleSelectOtherModel(reviewDetail.id, v)
                              } else {
                                setSelectedModels(prev => {
                                  const next = { ...prev }
                                  delete next[reviewDetail.id]
                                  return next
                                })
                              }
                            }}
                          />
                          <Button size="small" icon={<PlusOutlined />} onClick={() => setCreateModelOpen(true)}>
                            新建型号
                          </Button>
                        </Space>
                      </Descriptions.Item>
                      <Descriptions.Item label="价格">{reviewDetail.price != null ? `¥${reviewDetail.price}` : '-'}</Descriptions.Item>
                      <Descriptions.Item label="销量">{formatNumber(reviewDetail.sales_qty)}</Descriptions.Item>
                    </Descriptions>

                    <Card size="small" title="候选型号" bodyStyle={{ padding: 8 }}>
                      {(reviewDetail.candidates ?? []).length === 0 ? <Text type="secondary">暂无候选型号</Text> : (
                        <List
                          size="small"
                          dataSource={reviewDetail.candidates}
                          renderItem={(candidate: MatchCandidateOut) => (
                            <List.Item
                              actions={[
                                <Button
                                  size="small"
                                  type={candidate.rank === 1 ? 'primary' : 'default'}
                                  loading={confirmingIds.has(reviewDetail.id)}
                                  onClick={() => handleSelectCandidate(reviewDetail.id, candidate.model_id)}
                                >选用</Button>,
                              ]}
                            >
                              <Space>
                                <Tag color={candidate.rank === 1 ? 'blue' : 'default'}>#{candidate.rank}</Tag>
                                <Text code>[{candidate.brand_code ?? '-'}] {candidate.model_code ?? '-'}</Text>
                                {renderMatchSource(candidate.match_source)}
                                <Text type="secondary">分数 {candidate.score}</Text>
                              </Space>
                            </List.Item>
                          )}
                        />
                      )}
                    </Card>

                    <SameTitleBatchActions
                      detail={reviewDetail}
                      selectedModelId={selectedModels[reviewDetail.id]}
                      reason={reviewReason.trim() || undefined}
                      onDone={() => refreshReviewWorkbench(reviewDetail.id)}
                    />

                    <AttributeInsightCard detail={reviewDetail} />
                  </Space>
                )}
              </Card>
            </Col>
          </Row>
        </Card>
      )}

      {summary && readyCount > 0 && (
        <Card
          title={
            <Space>
              <span>已匹配 / 已确认条目</span>
              <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                价格预警仅提示，不影响确认或发布
              </span>
            </Space>
          }
        >
          <Table
            dataSource={reviewedData?.items ?? []}
            columns={[
              ...reviewedColumns,
              {
                title: '操作', width: 100, fixed: 'right' as const,
                render: (_: unknown, row: ReviewedMatchResultOut) => (
                  <Button size="small" type="link" onClick={() => openReselectModal(row)}>重新选择</Button>
                ),
              },
            ]}
            rowKey="id"
            size="small"
            loading={reviewedLoading}
            scroll={{ x: 1320 }}
            pagination={{
              current: reviewedPage,
              pageSize: 20,
              total: reviewedData?.total ?? 0,
              onChange: setReviewedPage,
              showTotal: t => `共 ${t} 条`,
            }}
          />
        </Card>
      )}

      <ReselectModal
        open={reselectOpen}
        matchId={reselectMatchId}
        onClose={() => { setReselectOpen(false); setReselectMatchId(null) }}
        onSuccess={handleReselectSuccess}
      />

      {summary && (summary.disabled ?? 0) > 0 && (
        <Card title={`禁用列表（${disabledTotal} 条）`}>
          <Table
            loading={disabledLoading}
            dataSource={disabledItems}
            rowKey="id"
            size="small"
            pagination={{
              current: disabledPage,
              total: disabledTotal,
              pageSize: 20,
              onChange: (p) => loadDisabled(p),
              showTotal: t => `共 ${t} 条`,
            }}
            columns={[
              { title: '商品名称', dataIndex: 'item_name', ellipsis: true },
              { title: '原始品牌', dataIndex: 'brand_raw', width: 120 },
              { title: '匹配状态', dataIndex: 'match_status', width: 100 },
              {
                title: '禁用原因', dataIndex: 'disable_reason', width: 120,
                render: (v: string | null) => v ? <Tag color="orange">{v}</Tag> : '-'
              },
              {
                title: '操作', width: 80, fixed: 'right' as const,
                render: (_: unknown, record: DisabledItem) => (
                  <Popconfirm
                    title="确认启用此条数据？"
                    onConfirm={async () => {
                      await enableMatch(record.id)
                      message.success('已启用')
                      loadDisabled(disabledPage)
                      getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
                    }}
                  >
                    <Button size="small" type="link">启用</Button>
                  </Popconfirm>
                ),
              },
            ]}
          />
        </Card>
      )}

      {summary && summary.total === 0 && (
        <Card>
          <Text type="secondary">该任务暂无匹配结果，请稍后刷新；如任务失败，可使用「重新匹配」。</Text>
        </Card>
      )}

      {summary && summary.total > 0 && summary.pending === 0 && (summary.text_only ?? 0) === 0 && (
        <Card>
          <Text type="secondary">暂无待确认条目，可点击「发布到分析库」发布已匹配结果。</Text>
        </Card>
      )}

      {publishJobs.length > 0 && (
        <Card title="发布历史">
          <Table
            dataSource={publishJobs}
            columns={publishColumns}
            rowKey="id"
            size="small"
            pagination={false}
          />
        </Card>
      )}

      <InterventionRuleModal
        open={interventionModalOpen}
        categoryCode={selectedJob?.category_code || selectedJob?.dispatch_category_code || null}
        detail={reviewDetail}
        onClose={() => setInterventionModalOpen(false)}
        onRulesChanged={() => {}}
      />

      <CreateModelModal
        open={createModelOpen}
        onCancel={() => setCreateModelOpen(false)}
        onCreated={handleCreatedModel}
        defaultCategoryCode={reviewDetail?.category_code ?? null}
        defaultCategoryName={reviewDetail?.category_name ?? null}
        metadataSpecs={reviewDetail?.metadata_specs ?? []}
        brandSuggestion={reviewDetail?.brand_raw ?? null}
      />

      <ProgressModal
        visible={exportProgressVisible}
        title="正在导出数据..."
        progress={exportProgress}
        errorMsg={exportError}
      />
    </Space>
  )
}
