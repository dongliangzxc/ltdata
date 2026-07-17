import { useMemo, useState } from 'react'
import type { Key } from 'react'
import {
  Card, Button, Table, Tag, Row, Col,
  Space, Statistic, Select, message, Tabs, Popconfirm
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EyeOutlined, AimOutlined, CheckCircleFilled, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import {
  deleteCleanJob,
  getCleanMonthlyPool,
  listCleanJobs,
  upsertMonthlyCleanTask,
} from '../../services/api'
import type { CleanJobItem, CleanMonthlyPoolItem, CleanJobListView } from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

type CleanJobStatus = 'created' | 'cleaning' | 'matching' | 'processing' | 'reviewing' | 'published' | 'failed' | 'done' | 'error' | 'archived'

type FilterState = {
  category_code?: string
  platform?: string
  month?: number
}

const platformOptions = [
  { value: 'jd', label: '京东' },
  { value: 'tmall', label: '天猫' },
  { value: 'taobao', label: '淘宝' },
  { value: 'douyin', label: '抖音' },
]

const platformLabelMap = platformOptions.reduce<Record<string, string>>((acc, option) => {
  acc[option.value] = option.label
  return acc
}, {})

const appendableStatuses = new Set(['reviewing', 'done', 'published'])
const processingStatuses = new Set(['created', 'cleaning', 'matching', 'processing'])

const statusMap: Record<CleanJobStatus, { label: string; color: string }> = {
  created: { label: '已创建', color: 'default' },
  cleaning: { label: '清洗中', color: 'processing' },
  matching: { label: '匹配中', color: 'processing' },
  processing: { label: '后台处理中', color: 'processing' },
  reviewing: { label: '待处理', color: 'orange' },
  published: { label: '已发布', color: 'green' },
  failed: { label: '失败', color: 'red' },
  done: { label: '待处理', color: 'orange' },
  error: { label: '失败', color: 'red' },
  archived: { label: '已删除', color: 'default' },
}

const formatNumber = (value?: number | null) => value ?? 0

const formatText = (value?: string | number | null) => value ?? '-'

const formatPlatform = (value?: string | null) => value ? (platformLabelMap[value] ?? value) : '-'

const cleanParams = (params: FilterState) => Object.fromEntries(
  Object.entries(params).filter(([, value]) => value != null && value !== '')
) as FilterState

const collectMonths = (monthlyPool: CleanMonthlyPoolItem[], jobs: CleanJobItem[]) => {
  const months = new Set<number>()
  monthlyPool.forEach(row => {
    if (row.month != null) months.add(Number(row.month))
  })
  jobs.forEach(row => {
    if (row.month != null) months.add(Number(row.month))
  })
  return Array.from(months)
    .filter(month => Number.isFinite(month))
    .sort((a, b) => b - a)
    .map(month => ({ value: month, label: String(month) }))
}

const renderStatus = (status: string) => {
  const statusInfo = statusMap[status as CleanJobStatus] ?? { label: status || '-', color: 'default' }
  return <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
}

const jobColumns = (
  onView: (id: number) => void,
  onEnter: (id: number) => void,
  onDelete: (id: number) => void,
  view: CleanJobListView,
): ColumnsType<CleanJobItem> => [
  {
    title: '任务名称', dataIndex: 'task_name', width: 180,
    render: (_: string | null | undefined, row) => row.task_name || row.scope_desc || `任务 #${row.id}`,
  },
  {
    title: '品类', dataIndex: 'category_code', width: 120,
    render: formatText,
  },
  {
    title: '平台', dataIndex: 'platform', width: 100,
    render: formatPlatform,
  },
  {
    title: '原始行', dataIndex: 'row_in', width: 90,
    render: formatNumber,
  },
  {
    title: '清洗后', dataIndex: 'row_out', width: 90,
    render: formatNumber,
  },
  {
    title: '待处理', dataIndex: 'pending_count', width: 90,
    render: formatNumber,
  },
  {
    title: '争议', dataIndex: 'disputed_count', width: 80,
    render: formatNumber,
  },
  {
    title: '可发布', dataIndex: 'publishable_count', width: 90,
    render: formatNumber,
  },
  {
    title: '状态', dataIndex: 'status', width: 110,
    render: (status: string, row) => {
      const cleanFinished = (status === 'done' || status === 'reviewing') && (row.pending_count ?? 0) === 0
      if (cleanFinished) {
        return <Tag icon={<CheckCircleFilled />} color="success">清洗完成</Tag>
      }
      return renderStatus(status)
    },
  },
  {
    title: '创建时间', dataIndex: 'created_at', width: 170,
    render: formatText,
  },
  {
    title: '操作', width: 220, fixed: 'right',
    render: (_: unknown, row) => (
      <Space size={4}>
        {view === 'active' && (
          <Button type="link" icon={<AimOutlined />} size="small" onClick={() => onEnter(row.id)}>进入处理</Button>
        )}
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => onView(row.id)}>预览</Button>
        {view === 'active' && (
          <Popconfirm
            title="确认删除该清洗任务？"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(row.id)}
          >
            <Button type="link" danger icon={<DeleteOutlined />} size="small">删除</Button>
          </Popconfirm>
        )}
      </Space>
    ),
  },
]

const getMonthlyQueueRowKey = (row: CleanMonthlyPoolItem) => `${row.category_code}-${row.platform ?? 'none'}-${row.month}`

const getQueueAction = (row: CleanMonthlyPoolItem) => {
  if (!row.platform) return { label: '缺少平台', disabled: true, action: 'blocked' as const }
  if (!row.existing_job_id) return { label: '创建任务', disabled: false, action: 'created' as const }
  if (row.existing_job_status && appendableStatuses.has(row.existing_job_status)) {
    return { label: '追加到任务', disabled: false, action: 'appended' as const }
  }
  if (row.existing_job_status && processingStatuses.has(row.existing_job_status)) {
    return { label: '处理中', disabled: true, action: 'processing' as const }
  }
  return { label: '先处理失败任务', disabled: true, action: 'blocked' as const }
}

const monthlyQueueColumns = (
  onUpsert: (row: CleanMonthlyPoolItem) => void,
  upsertingRowKey: string | null,
  operationDisabled: boolean,
): ColumnsType<CleanMonthlyPoolItem> => [
  {
    title: '品类', dataIndex: 'category_name', width: 140,
    render: (_: string | null | undefined, row) => row.category_name || row.category_code,
  },
  {
    title: '平台', dataIndex: 'platform', width: 100,
    render: formatPlatform,
  },
  {
    title: '月份', dataIndex: 'month', width: 100,
    render: formatText,
  },
  {
    title: '待入队数量', dataIndex: 'pending_count', width: 120,
    render: formatNumber,
  },
  {
    title: '已有任务', dataIndex: 'existing_job_name', width: 180,
    render: (_: string | null | undefined, row) => row.existing_job_name || (row.existing_job_id ? `任务 #${row.existing_job_id}` : '-'),
  },
  {
    title: '任务状态', dataIndex: 'existing_job_status', width: 110,
    render: (status?: string | null) => status ? renderStatus(status) : '-',
  },
  {
    title: '操作', width: 120, fixed: 'right',
    render: (_: unknown, row) => {
      const action = getQueueAction(row)
      const rowKey = getMonthlyQueueRowKey(row)
      const isCurrentRowUpserting = upsertingRowKey === rowKey
      return (
        <Button
          type="primary"
          size="small"
          disabled={action.disabled || operationDisabled || (!!upsertingRowKey && !isCurrentRowUpserting)}
          loading={isCurrentRowUpserting}
          onClick={() => onUpsert(row)}
        >
          {action.label}
        </Button>
      )
    },
  },
]

export default function CleanPage() {
  const navigate = useNavigate()
  const { options: categoryOptions, loading: categoryLoading } = useCategoryOptions()
  const [filters, setFilters] = useState<FilterState>({})
  const [jobView, setJobView] = useState<CleanJobListView>('active')
  const [upsertingRowKey, setUpsertingRowKey] = useState<string | null>(null)
  const [selectedMonthlyRowKeys, setSelectedMonthlyRowKeys] = useState<Key[]>([])
  const [batchUpserting, setBatchUpserting] = useState(false)

  const requestParams = useMemo(() => cleanParams(filters), [filters])
  const jobRequestParams = useMemo(() => ({ ...requestParams, view: jobView }), [requestParams, jobView])

  const {
    data: monthlyPoolData,
    loading: monthlyPoolLoading,
    refresh: refreshMonthlyPool,
  } = useRequest(() => getCleanMonthlyPool(requestParams).then(r => r.data), { refreshDeps: [requestParams] })

  const { data: jobsData, loading: jobsLoading, refresh: refreshJobs } = useRequest(
    () => listCleanJobs(jobRequestParams).then(r => r.data as CleanJobItem[]),
    { refreshDeps: [jobRequestParams] }
  )

  const jobs = jobsData ?? []
  const monthlyPool = monthlyPoolData ?? []
  const selectedMonthlyRowKeySet = useMemo(() => new Set(selectedMonthlyRowKeys), [selectedMonthlyRowKeys])
  const selectedActionableRows = useMemo(
    () => monthlyPool.filter(row => selectedMonthlyRowKeySet.has(getMonthlyQueueRowKey(row)) && !getQueueAction(row).disabled && row.platform),
    [monthlyPool, selectedMonthlyRowKeySet]
  )
  const monthOptions = useMemo(() => collectMonths(monthlyPool, jobsData ?? []), [monthlyPool, jobsData])
  const summary = useMemo(() => {
    const activeProcessingStatuses = new Set(['cleaning', 'matching', 'processing'])

    return {
      pendingTasks: jobs.filter(job => (job.pending_count ?? 0) + (job.disputed_count ?? 0) > 0).length,
      processingTasks: jobs.filter(job => activeProcessingStatuses.has(job.status)).length,
      publishableRecords: jobs.reduce((sum, job) => sum + (job.publishable_count ?? 0), 0),
      totalTasks: jobs.length,
    }
  }, [jobs])

  const { run: handleUpsertMonthlyTask } = useRequest(
    async (row: CleanMonthlyPoolItem) => {
      const rowKey = getMonthlyQueueRowKey(row)
      setUpsertingRowKey(rowKey)
      try {
        const action = getQueueAction(row).action
        const response = await upsertMonthlyCleanTask({
          category_code: row.category_code,
          platform: row.platform!,
          month: row.month,
          rules: { dedup: true },
        })
        message.success(action === 'appended' || response.data.action === 'appended' ? '已追加到清洗任务' : '已创建清洗任务')
        refreshMonthlyPool()
        refreshJobs()
      } finally {
        setUpsertingRowKey(null)
      }
    },
    { manual: true }
  )

  const { run: handleDeleteJob } = useRequest(
    async (jobId: number) => {
      await deleteCleanJob(jobId)
      message.success('清洗任务已删除')
      refreshMonthlyPool()
      refreshJobs()
    },
    { manual: true }
  )

  const handleBatchUpsertMonthlyTasks = async () => {
    if (batchUpserting) return

    const rows = selectedActionableRows
    if (rows.length === 0) {
      message.warning('请选择可创建或可追加的队列项')
      return
    }

    setBatchUpserting(true)
    let successCount = 0
    let failedCount = 0

    try {
      for (const row of rows) {
        try {
          await upsertMonthlyCleanTask({
            category_code: row.category_code,
            platform: row.platform!,
            month: row.month,
            rules: { dedup: true },
          })
          successCount += 1
        } catch {
          failedCount += 1
        }
      }

      if (failedCount === 0) {
        message.success(`已创建/追加 ${successCount} 个清洗任务`)
      } else if (successCount > 0) {
        message.warning(`已创建/追加 ${successCount} 个清洗任务，${failedCount} 个失败`)
      } else {
        message.error('批量创建/追加失败')
      }

      setSelectedMonthlyRowKeys([])
      refreshMonthlyPool()
      refreshJobs()
    } finally {
      setBatchUpserting(false)
    }
  }

  const monthlyRowSelection = {
    selectedRowKeys: selectedMonthlyRowKeys,
    onChange: (keys: Key[]) => {
      setSelectedMonthlyRowKeys(keys)
    },
    getCheckboxProps: (row: CleanMonthlyPoolItem) => ({
      disabled: getQueueAction(row).disabled || !!upsertingRowKey || batchUpserting,
    }),
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="待入清洗队列">
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Select
              allowClear
              showSearch
              placeholder="全部品类"
              loading={categoryLoading}
              options={categoryOptions}
              value={filters.category_code}
              onChange={value => setFilters(prev => ({ ...prev, category_code: value }))}
              optionFilterProp="label"
              style={{ width: '100%' }}
            />
          </Col>
          <Col span={6}>
            <Select
              allowClear
              placeholder="全部平台"
              options={platformOptions}
              value={filters.platform}
              onChange={value => setFilters(prev => ({ ...prev, platform: value }))}
              style={{ width: '100%' }}
            />
          </Col>
          <Col span={6}>
            <Select
              allowClear
              placeholder="全部月份"
              options={monthOptions}
              value={filters.month}
              onChange={value => setFilters(prev => ({ ...prev, month: value }))}
              style={{ width: '100%' }}
            />
          </Col>
        </Row>
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>已选择 {selectedActionableRows.length} 项</Col>
          <Col>
            <Button
              type="primary"
              disabled={selectedActionableRows.length === 0 || !!upsertingRowKey || batchUpserting}
              loading={batchUpserting}
              onClick={handleBatchUpsertMonthlyTasks}
            >
              批量创建/追加任务
            </Button>
          </Col>
        </Row>
        <Table
          dataSource={monthlyPool}
          columns={monthlyQueueColumns(handleUpsertMonthlyTask, upsertingRowKey, batchUpserting)}
          rowKey={getMonthlyQueueRowKey}
          rowSelection={monthlyRowSelection}
          size="small"
          loading={monthlyPoolLoading}
          scroll={{ x: 900 }}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Card title="清洗任务">
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Statistic title="待处理任务" value={summary.pendingTasks} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}><Statistic title="后台处理中" value={summary.processingTasks} valueStyle={{ color: '#1677ff' }} /></Col>
          <Col span={6}><Statistic title="可发布记录" value={summary.publishableRecords} valueStyle={{ color: '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="任务总数" value={summary.totalTasks} /></Col>
        </Row>
        <Tabs
          activeKey={jobView}
          onChange={key => setJobView(key as CleanJobListView)}
          items={[
            { key: 'active', label: '清洗任务' },
            { key: 'archived', label: '已删除' },
          ]}
        />
        <Table
          dataSource={jobs}
          columns={jobColumns(
            id => navigate(`/data-adjustment?clean_job_id=${id}`),
            id => navigate(`/match?job_id=${id}`),
            handleDeleteJob,
            jobView,
          )}
          rowKey="id"
          size="small"
          loading={jobsLoading}
          scroll={{ x: 1280 }}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </Space>
  )
}
