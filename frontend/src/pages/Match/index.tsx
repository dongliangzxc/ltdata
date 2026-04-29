import { useState, useEffect, useRef } from 'react'
import {
  Card, Select, Button, Table, Tag, Space, Typography, Input,
  message, Row, Col, Statistic, Tooltip, Progress, Alert, Popconfirm, InputNumber, Tabs
} from 'antd'
import { AimOutlined, CheckOutlined, StopOutlined, CloudUploadOutlined, LoadingOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import {
  listCleanJobs, runMatch, getMatchProgress, getMatchSummary, listPendingMatches,
  confirmMatch, listModels, runPublish, listPublishJobs,
  disableMatch, enableMatch, avgPriceDisable, listDisabled
} from '../../services/api'

const { Text } = Typography

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
}

type PendingItem = {
  id: number
  raw_data_id: number
  item_name: string
  brand_raw: string
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

export default function MatchPage() {
  const [searchParams] = useSearchParams()
  const [selectedJobId, setSelectedJobId] = useState<number | null>(
    searchParams.get('job_id') ? Number(searchParams.get('job_id')) : null
  )
  const [running, setRunning] = useState(false)
  const [matchProgress, setMatchProgress] = useState<MatchProgress | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [summary, setSummary] = useState<MatchSummary | null>(null)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [confirmingIds, setConfirmingIds] = useState<Set<number>>(new Set())
  const [selectedModels, setSelectedModels] = useState<Record<number, number>>({})
  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([])
  const [disabledItems, setDisabledItems] = useState<DisabledItem[]>([])
  const [disabledTotal, setDisabledTotal] = useState(0)
  const [disabledPage, setDisabledPage] = useState(1)
  const [disabledLoading, setDisabledLoading] = useState(false)
  const [avgPriceThreshold, setAvgPriceThreshold] = useState(200)
  const [disableReasonMap, setDisableReasonMap] = useState<Record<number, string>>({})
  const [activeTab, setActiveTab] = useState<'pending' | 'text_only'>('text_only')
  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 200 }).then(r => r.data),
  )
  const modelOptions: ModelOption[] = modelsData?.items ?? []

  const { data: pendingData, loading: pendingLoading, refresh: refreshPending } = useRequest(
    () => listPendingMatches(selectedJobId!, {
      keyword: keyword || undefined,
      page,
      page_size: 20,
      status: activeTab,
    }).then(r => r.data),
    {
      ready: selectedJobId != null && summary != null && (summary.pending > 0 || summary.text_only > 0),
      refreshDeps: [selectedJobId, keyword, page, activeTab],
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

  // 选任务后自动拉取摘要 + 发布历史
  useEffect(() => {
    if (!selectedJobId) return
    getMatchSummary(selectedJobId)
      .then(r => setSummary(r.data))
      .catch(() => setSummary(null))
    listPublishJobs(selectedJobId)
      .then(r => setPublishJobs(r.data.data ?? []))
      .catch(() => setPublishJobs([]))
    loadDisabled()
  }, [selectedJobId])

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
    // 开始轮询进度
    if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await getMatchProgress(selectedJobId)
        const p: MatchProgress = res.data
        setMatchProgress(p)
        if (p.status === 'done') {
          clearInterval(pollTimerRef.current!)
          pollTimerRef.current = null
          setRunning(false)
          message.success(`匹配完成：已匹配 ${p.matched} 条，待确认 ${p.total - p.matched} 条`)
          getMatchSummary(selectedJobId).then(r => setSummary(r.data))
          refreshPending()
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

  const handleConfirm = async (matchId: number) => {
    const modelId = selectedModels[matchId]
    if (!modelId) { message.warning('请先选择型号'); return }
    setConfirmingIds(prev => new Set(prev).add(matchId))
    try {
      await confirmMatch(matchId, { model_id: modelId })
      message.success('已确认')
      refreshPending()
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
      getMatchSummary(selectedJobId!).then(r => setSummary(r.data))
    } finally {
      setConfirmingIds(prev => { const s = new Set(prev); s.delete(matchId); return s })
    }
  }

  const handlePublish = async () => {
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    if (!summary || (summary.matched + summary.confirmed) === 0) {
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
      title: '指定型号', width: 260,
      render: (_: unknown, row: PendingItem) => (
        <Select
          showSearch
          placeholder="搜索品牌/型号码"
          style={{ width: '100%' }}
          size="small"
          allowClear
          filterOption={(input, option) =>
            (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
          }
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
  const readyCount = summary ? (summary?.url_matched ?? 0) + summary.matched + summary.confirmed : 0

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
              onChange={v => { setSelectedJobId(v); setSummary(null); setPage(1); setPublishJobs([]) }}
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

      {summary && (summary.pending > 0 || (summary.text_only ?? 0) > 0) && (
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
            <Input.Search
              placeholder="搜索宝贝名称"
              allowClear
              style={{ width: 220 }}
              onSearch={v => { setKeyword(v); setPage(1) }}
            />
          }
        >
          <Tabs
            activeKey={activeTab}
            onChange={key => {
              setActiveTab(key as 'pending' | 'text_only')
              setPage(1)
              setKeyword('')
            }}
            items={[
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
            ]}
          />
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
    </Space>
  )
}
