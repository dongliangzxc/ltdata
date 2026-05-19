import { useState, useEffect, useRef } from 'react'
import {
  Card, Select, Button, Table, Tag, Space, Typography, Input,
  message, Row, Col, Statistic, Tooltip, Progress, Alert, Popconfirm, InputNumber, Tabs,
  Popover, List,
} from 'antd'
import { AimOutlined, CheckOutlined, StopOutlined, CloudUploadOutlined, LoadingOutlined, LinkOutlined, SwapOutlined, DownloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import {
  listCleanJobs, runMatch, getMatchProgress, getMatchSummary, listPendingMatches,
  confirmMatch, listModels, runPublish, listPublishJobs,
  listReviewedMatches, updateMatchCoefficient,
  disableMatch, enableMatch, avgPriceDisable, listDisabled,
  applyAttrRules, listMissingAttrs,
  triggerExport, getExportJob, getDownloadUrl,
} from '../../services/api'
import type { MatchCandidateOut, ReviewedMatchResultOut, PriceFlag } from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
import ProgressModal from '../../components/ProgressModal'

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

const getAdjustedSalesQty = (row: ReviewedMatchResultOut, draftCoefficient?: number | null) => {
  if (draftCoefficient !== undefined) {
    const base = getBaseSalesQty(row)
    return base != null && draftCoefficient != null ? Math.round(base * draftCoefficient) : base
  }
  if (row.adjusted_sales_qty != null) return row.adjusted_sales_qty
  const base = getBaseSalesQty(row)
  return base != null && row.sales_coefficient != null ? Math.round(base * row.sales_coefficient) : base
}

type MatchSummary = {
  clean_job_id: number
  total: number
  url_matched: number
  matched: number
  text_only: number
  pending: number
  confirmed: number
  excluded: number
  disabled: number
  unidentified_brand?: number
  missing_attrs?: number
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
  candidates?: MatchCandidateOut[]
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

function MissingAttrsTabContent({
  cleanJobId,
  onApplyDone,
}: {
  cleanJobId: number
  onApplyDone: () => void
}) {
  const [page, setPage] = useState(1)
  const [applying, setApplying] = useState(false)
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const { options: categoryOptions } = useCategoryOptions()
  const { data, loading, refresh } = useRequest(
    () => listMissingAttrs(cleanJobId, {
      page, page_size: 20,
      ...(filterCategory ? { category_name: filterCategory } : {}),
    }).then(r => r.data),
    { refreshDeps: [cleanJobId, page, filterCategory] }
  )

  const handleApply = async () => {
    setApplying(true)
    try {
      const res = await applyAttrRules(cleanJobId)
      message.success(`重跑完成，共命中 ${res.data.matched_attrs} 个属性`)
      refresh()
      onApplyDone()
    } finally {
      setApplying(false)
    }
  }

  const columns = [
    { title: '商品名称', dataIndex: 'item_name', ellipsis: true },
    { title: '品牌', dataIndex: 'brand_raw', width: 120 },
    { title: '型号', dataIndex: 'model_code', width: 150 },
    { title: '品类', dataIndex: 'category_name', width: 120 },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert
        type="warning"
        showIcon
        message="以下商品型号已确认，但未匹配到属性规则。建议先前往「规则管理 → 属性规则」补充规则后重跑，或手动前往型号管理补充规格。"
        action={
          <Space>
            <Button size="small" onClick={() => window.open('/rules?tab=attr', '_blank')}>
              前往属性规则
            </Button>
            <Button size="small" type="primary" loading={applying} onClick={handleApply}>
              重跑属性规则
            </Button>
          </Space>
        }
      />
      <Select
        placeholder="品类筛选"
        allowClear
        style={{ width: 160 }}
        options={categoryOptions}
        value={filterCategory}
        onChange={v => { setFilterCategory(v); setPage(1) }}
      />
      <Table
        dataSource={data?.items ?? []}
        columns={columns}
        rowKey="id"
        size="small"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 20,
          total: data?.total ?? 0,
          onChange: setPage,
          showTotal: (t: number) => `共 ${t} 条`,
        }}
      />
    </Space>
  )
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
  const [categoryName, setCategoryName] = useState<string | undefined>()
  const [sortBy, setSortBy] = useState<string>('default')
  const [page, setPage] = useState(1)
  const [reviewedPage, setReviewedPage] = useState(1)
  const [confirmingIds, setConfirmingIds] = useState<Set<number>>(new Set())
  const [selectedModels, setSelectedModels] = useState<Record<number, number>>({})
  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([])
  const [disabledItems, setDisabledItems] = useState<DisabledItem[]>([])
  const [disabledTotal, setDisabledTotal] = useState(0)
  const [disabledPage, setDisabledPage] = useState(1)
  const [disabledLoading, setDisabledLoading] = useState(false)
  const [avgPriceThreshold, setAvgPriceThreshold] = useState(200)
  const [disableReasonMap, setDisableReasonMap] = useState<Record<number, string>>({})
  const [coefficientDrafts, setCoefficientDrafts] = useState<Record<number, number | null>>({})
  const [savingCoefficientIds, setSavingCoefficientIds] = useState<Set<number>>(new Set())
  const [activeTab, setActiveTab] = useState<'pending' | 'text_only' | 'unidentified_brand' | 'missing_attrs'>('text_only')
  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelSearchLoading, setModelSearchLoading] = useState(false)
  const { options: categoryOptions } = useCategoryOptions()
  const readyCount = summary ? (summary?.url_matched ?? 0) + summary.matched + summary.confirmed : 0

  const handleModelSearch = async (keyword: string) => {
    if (!keyword.trim()) return
    setModelSearchLoading(true)
    try {
      const res = await listModels({ keyword, page: 1, page_size: 50 }).then(r => r.data)
      setModelOptions(res.items ?? [])
    } finally {
      setModelSearchLoading(false)
    }
  }

  const { data: pendingData, loading: pendingLoading, refresh: refreshPending } = useRequest(
    () => listPendingMatches(selectedJobId!, {
      keyword: keyword || undefined,
      page,
      page_size: 20,
      status: activeTab === 'unidentified_brand' ? 'pending' : activeTab,
      ...(activeTab === 'unidentified_brand' ? { brand_identified: 0 } : {}),
      category_name: categoryName || undefined,
      sort_by: sortBy !== 'default' ? sortBy : undefined,
    }).then(r => r.data),
    {
      ready: selectedJobId != null && summary != null && activeTab !== 'missing_attrs' && (summary.pending > 0 || summary.text_only > 0 || (summary.unidentified_brand ?? 0) > 0),
      refreshDeps: [selectedJobId, keyword, page, activeTab, categoryName, sortBy],
    }
  )

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

  const handleConfirm = async (matchId: number) => {
    const modelId = selectedModels[matchId]
    if (!modelId) { message.warning('请先选择型号'); return }
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await confirmMatch(matchId, { model_id: modelId })
      message.success('已确认')
      refreshPending()
      refreshReviewed()
      getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handleExclude = async (matchId: number) => {
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await confirmMatch(matchId, { excluded: true })
      message.success('已排除')
      refreshPending()
      refreshReviewed()
      getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handleSelectCandidate = async (matchId: number, modelId: number) => {
    await confirmMatch(matchId, { model_id: modelId })
    message.success('已选用候选型号')
    refreshPending()
    refreshReviewed()
    getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
  }

  const handleSaveCoefficient = async (matchId: number) => {
    const coefficient = coefficientDrafts[matchId] ?? null
    setSavingCoefficientIds(prev => new Set(prev).add(matchId))
    try {
      const res = await updateMatchCoefficient(matchId, coefficient)
      setCoefficientDrafts(prev => ({ ...prev, [matchId]: res.data.sales_coefficient ?? null }))
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
      const res = await runPublish(selectedJobId)
      const { published_count, skipped_pending_count } = res.data.data
      message.success(`发布成功，共写入 ${published_count} 条到分析库`)
      if (skipped_pending_count > 0) {
        message.warning(
          `另有 ${skipped_pending_count} 条待确认（pending）条目未发布，如需发布请先人工确认`,
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

  const handleDisable = async (matchId: number) => {
    const reason = disableReasonMap[matchId]
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await disableMatch(matchId, reason || undefined)
      message.success('已禁用')
      refreshPending()
      refreshReviewed()
      getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
      loadDisabled()
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const pendingColumns = [
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string) => <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip>
    },
    { title: '原始品牌', dataIndex: 'brand_raw', width: 120 },
    {
      title: '销量', dataIndex: 'sales_qty', width: 80,
      render: (v: number | null) => v != null ? v.toLocaleString() : '-',
    },
    { title: '品类', dataIndex: 'category_name', width: 100,
      render: (v: string | null) => v ?? '-' },
    ...(activeTab === 'text_only' ? [
      {
        title: '匹配型号', width: 160,
        render: (_: unknown, row: PendingItem) =>
          row.brand_code && row.model_code
            ? (
              <span>
                <Text code style={{ fontSize: 12 }}>[{row.brand_code}] {row.model_code}</Text>
                {row.candidates && row.candidates.filter(c => c.rank > 1).length > 0 && (
                  <Popover
                    title="其他候选型号"
                    trigger="click"
                    content={
                      <List
                        size="small"
                        dataSource={row.candidates.filter(c => c.rank > 1)}
                        renderItem={(c: MatchCandidateOut) => (
                          <List.Item
                            actions={[
                              <Button
                                size="small"
                                onClick={() => handleSelectCandidate(row.id, c.model_id)}
                              >
                                选用
                              </Button>,
                            ]}
                          >
                            {c.model_code ?? '—'} ({c.brand_code ?? '—'}) · {c.match_source ?? '—'}
                          </List.Item>
                        )}
                      />
                    }
                  >
                    <SwapOutlined style={{ marginLeft: 4, cursor: 'pointer', color: '#1677ff' }} />
                  </Popover>
                )}
              </span>
            )
            : <Text type="secondary">-</Text>
      },
      {
        title: '商品链接', width: 80,
        render: (_: unknown, row: PendingItem) =>
          row.item_url
            ? <a href={row.item_url} target="_blank" rel="noreferrer"><LinkOutlined /> 查看</a>
            : '-'
      },
    ] : []),
    ...(activeTab !== 'text_only' ? [
      {
        title: '候选型号', width: 80,
        render: (_: unknown, row: PendingItem) => {
          const others = (row.candidates ?? []).filter(c => c.rank > 1)
          if (others.length === 0) return <Text type="secondary">—</Text>
          return (
            <Popover
              title="候选型号"
              trigger="click"
              content={
                <List
                  size="small"
                  dataSource={others}
                  renderItem={(c: MatchCandidateOut) => (
                    <List.Item
                      actions={[
                        <Button
                          size="small"
                          onClick={() => handleSelectCandidate(row.id, c.model_id)}
                        >
                          选用
                        </Button>,
                      ]}
                    >
                      {c.model_code ?? '—'} ({c.brand_code ?? '—'}) · {c.match_source ?? '—'}
                    </List.Item>
                  )}
                />
              }
            >
              <Button size="small" icon={<SwapOutlined />} type="link">
                {others.length} 个
              </Button>
            </Popover>
          )
        }
      },
    ] : []),
    {
      title: '指定型号', width: 260,
      render: (_: unknown, row: PendingItem) => (
        <Select
          showSearch
          placeholder="输入品牌/型号码搜索"
          style={{ width: '100%' }}
          size="small"
          allowClear
          filterOption={false}
          onSearch={handleModelSearch}
          loading={modelSearchLoading}
          options={modelOptions.map(m => ({
            value: m.id,
            label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
          }))}
          value={selectedModels[row.id]}
          onChange={v => setSelectedModels(prev => ({ ...prev, [row.id]: v }))}
        />
      )
    },
    {
      title: '属性',
      width: 100,
      render: (_: unknown, row: PendingItem) =>
        (row.attr_count ?? 0) > 0
          ? <Tag color="green">已补 {row.attr_count} 个</Tag>
          : <Tag color="default">未补</Tag>,
    },
    {
      title: '来源', width: 90,
      render: (_: unknown, row: PendingItem) => {
        const map: Record<string, { label: string; color: string }> = {
          's0':         { label: 'URL映射',  color: 'blue'   },
          'historical': { label: '历史库',   color: 'purple' },
          's0.5':       { label: '规则',     color: 'cyan'   },
          's1':         { label: '算法S1',   color: 'green'  },
          's2':         { label: '算法S2',   color: 'green'  },
          's3':         { label: '算法S3',   color: 'green'  },
          's4':         { label: '算法S4',   color: 'orange' },
        }
        const src = row.match_source
        if (!src) return <Tag color="default">未知</Tag>
        const entry = map[src]
        return entry
          ? <Tag color={entry.color}>{entry.label}</Tag>
          : <Tag>{src}</Tag>
      },
    },
    {
      title: '操作', width: 180, fixed: 'right' as const,
      render: (_: unknown, row: PendingItem) => (
        <Space size={4}>
          <Button
            type="primary" size="small" icon={<CheckOutlined />}
            loading={confirmingIds.has(row.id)}
            onClick={() => handleConfirm(row.id)}
          >确认</Button>
          <Button
            size="small" danger icon={<StopOutlined />}
            loading={confirmingIds.has(row.id)}
            onClick={() => handleExclude(row.id)}
          >排除</Button>
          <Popconfirm
            title={
              <Space direction="vertical" size={4}>
                <span>选择禁用原因</span>
                <Select
                  size="small"
                  style={{ width: 130 }}
                  placeholder="原因(可选)"
                  allowClear
                  onChange={(v: string) => setDisableReasonMap(prev => ({ ...prev, [row.id]: v }))}
                  options={[
                    { value: '商用', label: '商用' },
                    { value: '配件', label: '配件' },
                    { value: 'avg_price', label: '均价过低' },
                    { value: '其他', label: '其他' },
                  ]}
                />
              </Space>
            }
            onConfirm={() => handleDisable(row.id)}
            okText="禁用"
            cancelText="取消"
          >
            <Button
              size="small"
              loading={confirmingIds.has(row.id)}
            >禁用</Button>
          </Popconfirm>
        </Space>
      )
    },
  ]

  const reviewedColumns = [
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string | null) => v ? <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip> : '-'
    },
    { title: '品牌', dataIndex: 'brand_raw', width: 110, render: (v: string | null) => v ?? '-' },
    {
      title: '匹配型号', width: 160,
      render: (_: unknown, row: ReviewedMatchResultOut) =>
        row.brand_code && row.model_code
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
            onChange={v => setCoefficientDrafts(prev => ({ ...prev, [row.id]: v == null ? null : Number(v) }))}
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
      render: (_: unknown, row: ReviewedMatchResultOut) => formatNumber(getAdjustedSalesQty(row, coefficientDrafts[row.id])),
    },
    {
      title: '状态', dataIndex: 'match_status', width: 90,
      render: (v: string) => <Tag color={v === 'confirmed' ? 'blue' : 'green'}>{v}</Tag>,
    },
    {
      title: '来源', width: 90,
      render: (_: unknown, row: ReviewedMatchResultOut) => row.match_source ? <Tag>{row.match_source}</Tag> : '-'
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
      render: (v: string) => new Date(v).toLocaleString('zh-CN')
    },
  ]

  const doneJobs = (jobsData ?? []).filter((j: { status: string }) => j.status === 'done')

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>选择清洗任务：</Text>
          </Col>
          <Col flex="200px">
            <Select
              style={{ width: '100%' }}
              placeholder="选择任务"
              value={selectedJobId}
              onChange={v => { setSelectedJobId(v); setSummary(null); setPage(1); setReviewedPage(1); setPublishJobs([]); setCoefficientDrafts({}) }}
              options={doneJobs.map((j: { id: number; created_at: string; row_out: number }) => ({
                value: j.id,
                label: `任务#${j.id}（${j.row_out}条，${new Date(j.created_at).toLocaleDateString('zh-CN')}）`,
              }))}
            />
          </Col>
          <Col>
            <Button
              type="primary"
              icon={<AimOutlined />}
              loading={running}
              onClick={handleRunMatch}
              disabled={!selectedJobId}
            >
              执行匹配
            </Button>
          </Col>
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
            <Col span={3}><Statistic title="URL匹配" value={summary.url_matched ?? 0} valueStyle={{ color: '#389e0d' }} /></Col>
            <Col span={3}><Statistic title="文本匹配" value={summary.matched} valueStyle={{ color: '#3f8600' }} /></Col>
            <Col span={3}><Statistic title="URL待审" value={summary.text_only ?? 0} valueStyle={{ color: '#d48806' }} /></Col>
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

      {summary && (summary.pending > 0 || (summary.text_only ?? 0) > 0 || (summary.unidentified_brand ?? 0) > 0 || (summary.missing_attrs ?? 0) > 0) && (
        <Card
          title={
            <Space>
              <span>待处理条目</span>
              <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                URL待审 {summary.text_only ?? 0} 条 · 待确认 {summary.pending} 条
              </span>
            </Space>
          }
          extra={
            <Space>
              <Select
                placeholder="品类筛选"
                allowClear
                style={{ width: 140 }}
                options={categoryOptions}
                onChange={v => { setCategoryName(v); setPage(1) }}
              />
              <Select
                value={sortBy}
                style={{ width: 130 }}
                onChange={v => { setSortBy(v); setPage(1) }}
                options={[
                  { value: 'default', label: '默认排序' },
                  { value: 'sales_qty_desc', label: '销量从高到低' },
                  { value: 'sales_qty_asc', label: '销量从低到高' },
                ]}
              />
              <Input.Search
                placeholder="搜索宝贝名称"
                allowClear
                style={{ width: 220 }}
                onSearch={v => { setKeyword(v); setPage(1) }}
              />
            </Space>
          }
        >
          <Tabs
            activeKey={activeTab}
            onChange={key => {
              setActiveTab(key as 'pending' | 'text_only' | 'unidentified_brand' | 'missing_attrs')
              setPage(1)
              setKeyword('')
              setCategoryName(undefined)
              setSortBy('default')
            }}
            items={[
              {
                key: 'unidentified_brand',
                label: (
                  <span>
                    未识别品牌
                    {(summary?.unidentified_brand ?? 0) > 0 && (
                      <span style={{
                        marginLeft: 6, background: '#722ed1', color: '#fff',
                        borderRadius: 10, padding: '0 6px', fontSize: 11,
                      }}>
                        {summary?.unidentified_brand}
                      </span>
                    )}
                  </span>
                ),
                children: null,
              },
              {
                key: 'text_only',
                label: (
                  <span>
                    URL待审
                    {(summary.text_only ?? 0) > 0 && (
                      <span style={{
                        marginLeft: 6, background: '#d48806', color: '#fff',
                        borderRadius: 10, padding: '0 6px', fontSize: 11,
                      }}>
                        {summary.text_only}
                      </span>
                    )}
                  </span>
                ),
                children: null,
              },
              {
                key: 'pending',
                label: (
                  <span>
                    待确认
                    {summary.pending > 0 && (
                      <span style={{
                        marginLeft: 6, background: '#d46b08', color: '#fff',
                        borderRadius: 10, padding: '0 6px', fontSize: 11,
                      }}>
                        {summary.pending}
                      </span>
                    )}
                  </span>
                ),
                children: null,
              },
              {
                key: 'missing_attrs',
                label: (
                  <span>
                    未补属性
                    {(summary?.missing_attrs ?? 0) > 0 && (
                      <Tag color="orange" style={{ marginLeft: 4 }}>{summary?.missing_attrs}</Tag>
                    )}
                  </span>
                ),
                children: activeTab === 'missing_attrs' && selectedJobId ? (
                  <MissingAttrsTabContent
                    cleanJobId={selectedJobId}
                    onApplyDone={() => getMatchSummary(selectedJobId).then(r => setSummary(r.data))}
                  />
                ) : null,
              },
            ]}
          />
          {activeTab === 'unidentified_brand' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                <span>
                  以下商品的品牌在系统中未能识别，建议先前往「规则管理 → 品牌写法库」补充写法后重新执行匹配，效率高于逐条人工确认。
                  <Button type="link" size="small" onClick={() => window.open('/rules', '_blank')}>前往规则管理 →</Button>
                </span>
              }
            />
          )}
          {activeTab !== 'missing_attrs' && (
            <Table
              dataSource={pendingData?.items ?? []}
              columns={pendingColumns}
              rowKey="id"
              size="small"
              loading={pendingLoading}
              scroll={{ x: 800 }}
              pagination={{
                current: page,
                pageSize: 20,
                total: pendingData?.total ?? 0,
                onChange: setPage,
                showTotal: t => `共 ${t} 条`,
              }}
            />
          )}
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
            columns={reviewedColumns}
            rowKey="id"
            size="small"
            loading={reviewedLoading}
            scroll={{ x: 1200 }}
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
          <Text type="secondary">该任务尚未执行匹配，请点击「执行匹配」开始匹配。</Text>
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

      <ProgressModal
        visible={exportProgressVisible}
        title="正在导出数据..."
        progress={exportProgress}
        errorMsg={exportError}
      />
    </Space>
  )
}
