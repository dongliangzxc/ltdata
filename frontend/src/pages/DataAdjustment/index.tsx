import { useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import { Alert, Card, Empty, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import { listCleanJobs, previewCleanJob } from '../../services/api'
import type { CleanJobItem, CleanJobListView } from '../../services/api'
import {
  cleanPreviewColumns,
  formatNumber,
  formatPlatform,
  formatText,
} from '../Clean/cleanPreviewTable'
import type { CleanPreviewResponse, TaggedCleanPreviewResponse } from '../Clean/cleanPreviewTable'

const { Title, Text } = Typography

const PAGE_SIZE = 20
const DEFAULT_VIEW: CleanJobListView = 'active'

type SelectedRowKey = Key[]

const statusConfig: Record<string, { label: string; color: string }> = {
  created: { label: '已创建', color: 'blue' },
  cleaning: { label: '清洗中', color: 'processing' },
  matching: { label: '匹配中', color: 'processing' },
  processing: { label: '处理中', color: 'processing' },
  reviewing: { label: '待审核', color: 'orange' },
  published: { label: '已发布', color: 'green' },
  failed: { label: '失败', color: 'red' },
  done: { label: '待处理', color: 'orange' },
  error: { label: '失败', color: 'red' },
  archived: { label: '已删除', color: 'default' },
}

const formatStatus = (status?: string | null) => {
  if (!status) return <Tag>未知</Tag>
  const config = statusConfig[status] ?? { label: status, color: 'default' }
  return <Tag color={config.color}>{config.label}</Tag>
}

export default function DataAdjustmentPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [view, setView] = useState<CleanJobListView>(DEFAULT_VIEW)
  const [selectedJobId, setSelectedJobId] = useState<number | undefined>(() => {
    const cleanJobId = Number(searchParams.get('clean_job_id'))
    return Number.isFinite(cleanJobId) && cleanJobId > 0 ? cleanJobId : undefined
  })
  const [previewPage, setPreviewPage] = useState(1)

  const {
    data: jobs = [],
    loading: jobsLoading,
  } = useRequest(
    async () => {
      const response = await listCleanJobs({ view })
      return response.data as CleanJobItem[]
    },
    {
      refreshDeps: [view],
      onError: () => message.error('清洗任务加载失败'),
    }
  )

  const selectedJob = useMemo(
    () => jobs.find(job => job.id === selectedJobId),
    [jobs, selectedJobId]
  )

  useEffect(() => {
    if (!selectedJobId || jobsLoading || jobs.length === 0) return
    if (!selectedJob) {
      message.warning('未找到 URL 中指定的清洗任务，请重新选择')
      setSelectedJobId(undefined)
      setSearchParams({}, { replace: true })
    }
  }, [jobs, jobsLoading, selectedJob, selectedJobId, setSearchParams])

  const { data: previewData, loading: previewLoading } = useRequest(
    async () => {
      const jobId = selectedJobId!
      const response = await previewCleanJob(jobId, { page: previewPage, page_size: PAGE_SIZE })
      return { ...(response.data as CleanPreviewResponse), jobId }
    },
    {
      ready: selectedJobId != null,
      refreshDeps: [selectedJobId, previewPage],
      onError: () => message.error('数据调整明细加载失败'),
    }
  )

  const currentPreviewData: TaggedCleanPreviewResponse | undefined = previewData?.jobId === selectedJobId ? previewData : undefined

  const handleSelectJob = (jobId: number) => {
    setSelectedJobId(jobId)
    setPreviewPage(1)
    setSearchParams({ clean_job_id: String(jobId) })
  }

  const jobColumns: ColumnsType<CleanJobItem> = [
    { title: '任务ID', dataIndex: 'id', width: 90 },
    { title: '任务名称', dataIndex: 'task_name', ellipsis: true, render: formatText },
    { title: '品类', dataIndex: 'category_code', width: 160, render: formatText },
    { title: '平台', dataIndex: 'platform', width: 100, render: formatPlatform },
    { title: '月份', dataIndex: 'month', width: 100, render: formatText },
    { title: '清洗后', dataIndex: 'row_out', width: 90, render: formatNumber },
    { title: '可发布', dataIndex: 'publishable_count', width: 90, render: formatNumber },
    { title: '状态', dataIndex: 'status', width: 110, render: formatStatus },
  ]

  const selectedRowKeys: SelectedRowKey = selectedJobId ? [selectedJobId] : []

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Title level={3} style={{ margin: 0 }}>数据调整</Title>

      <Card
        title="清洗任务选择"
        extra={
          <Space>
            <Text type="secondary">任务范围</Text>
            <Select<CleanJobListView>
              value={view}
              style={{ width: 120 }}
              onChange={nextView => {
                setView(nextView)
                setSelectedJobId(undefined)
                setPreviewPage(1)
                setSearchParams({}, { replace: true })
              }}
              options={[
                { value: 'active', label: '进行中' },
                { value: 'archived', label: '已删除' },
                { value: 'all', label: '全部' },
              ]}
            />
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={jobColumns}
          dataSource={jobs}
          loading={jobsLoading}
          size="middle"
          rowSelection={{
            type: 'radio',
            selectedRowKeys,
            onChange: keys => {
              const nextJobId = Number(keys[0])
              if (Number.isFinite(nextJobId)) handleSelectJob(nextJobId)
            },
          }}
          onRow={record => ({
            onClick: () => handleSelectJob(record.id),
          })}
          pagination={{ pageSize: 10, showSizeChanger: false }}
        />
      </Card>

      <Card title={selectedJob ? `数据调整明细：${selectedJob.task_name || `任务 ${selectedJob.id}`}` : '数据调整明细'}>
        {!selectedJobId ? (
          <Empty description="先选择清洗任务" />
        ) : !selectedJob ? (
          <Alert type="warning" showIcon message="未找到已选择的清洗任务" description="请从上方列表重新选择清洗任务。" />
        ) : (
          <Table
            rowKey={(row, index) => row.id ?? `${selectedJobId}-${previewPage}-${index}`}
            columns={cleanPreviewColumns}
            dataSource={currentPreviewData?.items ?? []}
            loading={previewLoading}
            scroll={{ x: 900 }}
            pagination={{
              current: previewPage,
              pageSize: PAGE_SIZE,
              total: currentPreviewData?.total ?? 0,
              onChange: setPreviewPage,
              showSizeChanger: false,
              showTotal: total => `共 ${total} 条`,
            }}
          />
        )}
      </Card>
    </Space>
  )
}
