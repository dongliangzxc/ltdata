import { useState, useEffect } from 'react'
import {
  Card, Select, Button, Table, Tag, Space, Typography, Input,
  message, Row, Col, Statistic, Tooltip
} from 'antd'
import { AimOutlined, CheckOutlined, StopOutlined, CloudUploadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import {
  listCleanJobs, runMatch, getMatchSummary, listPendingMatches,
  confirmMatch, listModels, runPublish, listPublishJobs
} from '../../services/api'

const { Text } = Typography

type MatchSummary = {
  clean_job_id: number
  total: number
  matched: number
  pending: number
  confirmed: number
  excluded: number
}

type PendingItem = {
  id: number
  raw_data_id: number
  item_name: string
  brand_raw: string
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

export default function MatchPage() {
  const [searchParams] = useSearchParams()
  const [selectedJobId, setSelectedJobId] = useState<number | null>(
    searchParams.get('job_id') ? Number(searchParams.get('job_id')) : null
  )
  const [running, setRunning] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [summary, setSummary] = useState<MatchSummary | null>(null)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [confirmingIds, setConfirmingIds] = useState<Set<number>>(new Set())
  const [selectedModels, setSelectedModels] = useState<Record<number, number>>({})
  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([])

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 200 }).then(r => r.data),
  )
  const modelOptions: ModelOption[] = modelsData?.items ?? []

  const { data: pendingData, loading: pendingLoading, refresh: refreshPending } = useRequest(
    () => listPendingMatches(selectedJobId!, { keyword: keyword || undefined, page, page_size: 20 }).then(r => r.data),
    { ready: selectedJobId != null && summary != null && summary.pending > 0, refreshDeps: [selectedJobId, keyword, page] }
  )

  // 选任务后自动拉取摘要 + 发布历史
  useEffect(() => {
    if (!selectedJobId) return
    getMatchSummary(selectedJobId)
      .then(r => setSummary(r.data))
      .catch(() => setSummary(null))
    listPublishJobs(selectedJobId)
      .then(r => setPublishJobs(r.data.data ?? []))
      .catch(() => setPublishJobs([]))
  }, [selectedJobId])

  const handleRunMatch = async () => {
    if (!selectedJobId) { message.warning('请先选择清洗任务'); return }
    setRunning(true)
    try {
      const res = await runMatch(selectedJobId)
      setSummary(res.data)
      refreshPending()
      message.success(`匹配完成：已匹配 ${res.data.matched} 条，待确认 ${res.data.pending} 条`)
    } finally {
      setRunning(false)
    }
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
      const { published_count } = res.data.data
      message.success(`发布成功，共写入 ${published_count} 条到分析库`)
      // 刷新发布历史
      listPublishJobs(selectedJobId).then(r => setPublishJobs(r.data.data ?? []))
    } finally {
      setPublishing(false)
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
      title: '操作', width: 110, fixed: 'right' as const,
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
  const readyCount = summary ? summary.matched + summary.confirmed : 0

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

      {summary && (
        <Card>
          <Row gutter={24}>
            <Col span={4}><Statistic title="总条数" value={summary.total} /></Col>
            <Col span={4}><Statistic title="自动匹配" value={summary.matched} valueStyle={{ color: '#3f8600' }} /></Col>
            <Col span={4}><Statistic title="待确认" value={summary.pending} valueStyle={{ color: '#d46b08' }} /></Col>
            <Col span={4}><Statistic title="已人工确认" value={summary.confirmed} valueStyle={{ color: '#1677ff' }} /></Col>
            <Col span={4}><Statistic title="已排除" value={summary.excluded} valueStyle={{ color: '#cf1322' }} /></Col>
            <Col span={4}>
              <Statistic
                title="匹配率"
                value={summary.total ? Math.round((summary.matched + summary.confirmed) / summary.total * 100) : 0}
                suffix="%"
                valueStyle={{ color: '#3f8600' }}
              />
            </Col>
          </Row>
        </Card>
      )}

      {summary && summary.pending > 0 && (
        <Card
          title={`待确认条目（${summary.pending} 条）`}
          extra={
            <Input.Search
              placeholder="搜索宝贝名称"
              allowClear
              style={{ width: 220 }}
              onSearch={v => { setKeyword(v); setPage(1) }}
            />
          }
        >
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

      {summary && summary.pending === 0 && (
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
