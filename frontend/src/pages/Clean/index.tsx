import { useMemo, useState } from 'react'
import {
  Card, Button, Table, Tag, Modal, Row, Col,
  Space, Statistic
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EyeOutlined, AimOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import {
  listCleanJobs, previewCleanJob,
} from '../../services/api'
import type { CleanJobItem } from '../../services/api'

type CleanJobStatus = 'created' | 'cleaning' | 'matching' | 'processing' | 'reviewing' | 'published' | 'failed' | 'done' | 'error'

type CleanPreviewRow = {
  id?: number
  platform?: string | null
  month?: string | number | null
  brand_std?: string | null
  brand?: string | null
  item_name?: string | null
  sales_qty?: number | null
  sales_amount?: number | null
}

type CleanPreviewResponse = {
  total: number
  items: CleanPreviewRow[]
}

type TaggedCleanPreviewResponse = CleanPreviewResponse & {
  jobId: number
}

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
}

const formatNumber = (value?: number | null) => value ?? 0

const formatText = (value?: string | number | null) => value ?? '-'

const renderStatus = (status: string) => {
  const statusInfo = statusMap[status as CleanJobStatus] ?? { label: status || '-', color: 'default' }
  return <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
}

const jobColumns = (onPreview: (id: number) => void, onEnter: (id: number) => void): ColumnsType<CleanJobItem> => [
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
    render: formatText,
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
    title: '状态', dataIndex: 'status', width: 100,
    render: renderStatus,
  },
  {
    title: '创建时间', dataIndex: 'created_at', width: 170,
    render: formatText,
  },
  {
    title: '操作', width: 160, fixed: 'right',
    render: (_: unknown, row) => (
      <Space size={4}>
        <Button type="link" icon={<AimOutlined />} size="small" onClick={() => onEnter(row.id)}>进入处理</Button>
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => onPreview(row.id)}>预览</Button>
      </Space>
    ),
  },
]

const previewCols: ColumnsType<CleanPreviewRow> = [
  {
    title: '平台', dataIndex: 'platform', width: 90,
    render: formatText,
  },
  {
    title: '月份', dataIndex: 'month', width: 90,
    render: formatText,
  },
  {
    title: '品牌', dataIndex: 'brand_std', width: 110,
    render: (_: string | null | undefined, row) => row.brand_std || row.brand || '-',
  },
  {
    title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
    render: formatText,
  },
  {
    title: '销量', dataIndex: 'sales_qty', width: 80,
    render: formatNumber,
  },
  {
    title: '销售额', dataIndex: 'sales_amount', width: 110,
    render: (v: number | null | undefined) => v != null ? `¥${Number(v).toLocaleString()}` : '-',
  },
]

export default function CleanPage() {
  const navigate = useNavigate()
  const [previewJobId, setPreviewJobId] = useState<number | null>(null)
  const [previewPage, setPreviewPage] = useState(1)

  const { data: jobsData, loading: jobsLoading } = useRequest(() => listCleanJobs().then(r => r.data as CleanJobItem[]))

  const jobs = jobsData ?? []
  const summary = useMemo(() => {
    const processingStatuses = new Set(['cleaning', 'matching', 'processing'])

    return {
      pendingTasks: jobs.filter(job => (job.pending_count ?? 0) + (job.disputed_count ?? 0) > 0).length,
      processingTasks: jobs.filter(job => processingStatuses.has(job.status)).length,
      publishableRecords: jobs.reduce((sum, job) => sum + (job.publishable_count ?? 0), 0),
      totalTasks: jobs.length,
    }
  }, [jobs])

  const { data: previewData, loading: previewLoading } = useRequest(
    async () => {
      const jobId = previewJobId!
      const response = await previewCleanJob(jobId, { page: previewPage, page_size: 20 })
      return { ...(response.data as CleanPreviewResponse), jobId }
    },
    { ready: previewJobId != null, refreshDeps: [previewJobId, previewPage] }
  )
  const currentPreviewData: TaggedCleanPreviewResponse | undefined = previewData?.jobId === previewJobId ? previewData : undefined

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="清洗任务">
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Statistic title="待处理任务" value={summary.pendingTasks} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}><Statistic title="后台处理中" value={summary.processingTasks} valueStyle={{ color: '#1677ff' }} /></Col>
          <Col span={6}><Statistic title="可发布记录" value={summary.publishableRecords} valueStyle={{ color: '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="任务总数" value={summary.totalTasks} /></Col>
        </Row>
        <Table
          dataSource={jobs}
          columns={jobColumns(
            id => { setPreviewJobId(id); setPreviewPage(1) },
            id => navigate(`/match?job_id=${id}`)
          )}
          rowKey="id"
          size="small"
          loading={jobsLoading}
          scroll={{ x: 1280 }}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title={`清洗结果预览（任务 #${previewJobId}）`}
        open={previewJobId != null}
        onCancel={() => setPreviewJobId(null)}
        footer={null}
        width={1000}
      >
        <Table
          dataSource={currentPreviewData?.items ?? []}
          columns={previewCols}
          rowKey={(row, index) => String(row.id ?? index)}
          size="small"
          loading={previewLoading}
          scroll={{ x: 800 }}
          pagination={{
            current: previewPage,
            pageSize: 20,
            total: currentPreviewData?.total ?? 0,
            onChange: setPreviewPage,
            showSizeChanger: false,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Modal>
    </Space>
  )
}
