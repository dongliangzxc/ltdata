import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card, Select, Input, Button, Table, Space, Typography, message,
  Row, Col, Tag, Tooltip
} from 'antd'
import { ExportOutlined, DownloadOutlined, ReloadOutlined, LoadingOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { getDownloadUrl, listCleanJobs, listExportJobs, triggerExport, type CleanJobItem } from '../../services/api'

const { Text } = Typography

type ExportJobItem = {
  id: number
  clean_job_id: number | null
  months: number[] | null
  category_code: string | null
  platforms: string[] | null
  filename_prefix: string
  status: 'pending' | 'running' | 'done' | 'error'
  filename: string | null
  token: string | null
  rows: number | null
  pending_rows: number | null
  error_msg: string | null
  created_at: string
}

export default function ExportPage() {
  const [selectedMonths, setSelectedMonths] = useState<number[]>([])
  const [selectedCategoryCode, setSelectedCategoryCode] = useState<string | undefined>(undefined)
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([])
  const [filenamePrefix, setFilenamePrefix] = useState('已处理数据')
  const [triggering, setTriggering] = useState(false)
  const [exportJobs, setExportJobs] = useState<ExportJobItem[]>([])
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: filterData } = useRequest(() => getExportFilters().then(r => r.data))

  const filterOptions = filterData ?? { months: [], platforms: [], categories: [] }

  const loadExportJobs = () => {
    listExportJobs().then(r => setExportJobs(r.data.data ?? [])).catch(() => {})
  }

  useEffect(() => {
    loadExportJobs()
  }, [])

  useEffect(() => {
    const hasPending = exportJobs.some(j => j.status === 'pending' || j.status === 'running')
    if (hasPending) {
      if (!pollTimerRef.current) {
        pollTimerRef.current = setInterval(loadExportJobs, 2000)
      }
    } else if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [exportJobs])

  const handleTrigger = async () => {
    if (selectedMonths.length === 0) { message.warning('请选择月度'); return }
    if (!selectedCategoryCode) { message.warning('请选择品类'); return }
    if (selectedPlatforms.length === 0) { message.warning('请选择平台'); return }
    setTriggering(true)
    try {
      await triggerExport({
        months: selectedMonths,
        category_code: selectedCategoryCode,
        platforms: selectedPlatforms,
        filename_prefix: filenamePrefix,
      })
      message.success('导出任务已提交，文件生成后可在下方下载')
      loadExportJobs()
    } finally {
      setTriggering(false)
    }
  }

  const columns = [
    { title: '月度', dataIndex: 'months', key: 'months', render: (months: number[] | null) => months?.length ? months.join('、') : '-' },
    { title: '品类', dataIndex: 'category_code', key: 'category_code', render: (value: string | null) => value || '-' },
    { title: '平台', dataIndex: 'platforms', key: 'platforms', render: (value: string[] | null) => value?.length ? value.join('、') : '-' },
    { title: '文件名前缀', dataIndex: 'filename_prefix', key: 'filename_prefix' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (_: string, record: ExportJobItem) => <Tag color={record.status === 'done' ? 'success' : record.status === 'error' ? 'error' : record.status === 'running' ? 'processing' : 'default'}>{record.status === 'done' ? '已完成' : record.status === 'error' ? '失败' : record.status === 'running' ? '生成中' : '排队中'}</Tag> },
    { title: '已匹配行', dataIndex: 'rows', key: 'rows', render: (value: number | null) => value ?? '-' },
    { title: '待确认行', dataIndex: 'pending_rows', key: 'pending_rows', render: (value: number | null) => value ?? '-' },
    { title: '提交时间', dataIndex: 'created_at', key: 'created_at', render: (value: string) => value?.slice(0, 19).replace('T', ' ') ?? '-' },
    { title: '操作', key: 'action', render: (_: unknown, record: ExportJobItem) => record.status === 'done' && record.token ? <Button type="link" icon={<DownloadOutlined />} href={getDownloadUrl(record.token)}>下载</Button> : <span>{record.error_msg || '—'}</span> },
  ]

  return (
    <div className="space-y-4">
      <Card title="导出配置">
        <Row gutter={16}>
          <Col span={8}>
            <Text strong>月度</Text>
            <Select mode="multiple" style={{ width: '100%', marginTop: 8 }} placeholder="选择月度" value={selectedMonths} onChange={setSelectedMonths} options={filterOptions.months.map(month => ({ value: month, label: String(month) }))} />
          </Col>
          <Col span={8}>
            <Text strong>品类</Text>
            <Select showSearch style={{ width: '100%', marginTop: 8 }} placeholder="选择品类" value={selectedCategoryCode} onChange={setSelectedCategoryCode} options={filterOptions.categories} />
          </Col>
          <Col span={8}>
            <Text strong>平台</Text>
            <Select mode="multiple" style={{ width: '100%', marginTop: 8 }} placeholder="选择平台" value={selectedPlatforms} onChange={setSelectedPlatforms} options={filterOptions.platforms.map(platform => ({ value: platform, label: platform }))} />
          </Col>
        </Row>
        <div style={{ marginTop: 16 }}>
          <Text strong>文件名前缀</Text>
          <Input style={{ marginTop: 8, maxWidth: 360 }} value={filenamePrefix} onChange={e => setFilenamePrefix(e.target.value)} placeholder="如：202507匹配结果" />
        </div>
        <Button style={{ marginTop: 16 }} type="primary" icon={<ExportOutlined />} onClick={handleTrigger} loading={triggering} disabled={selectedMonths.length === 0 || !selectedCategoryCode || selectedPlatforms.length === 0}>提交导出任务</Button>
      </Card>

      <Card title="导出历史" extra={<Button icon={<ReloadOutlined />} onClick={loadExportJobs}>刷新</Button>}>
        <Table rowKey="id" columns={columns as never} dataSource={exportJobs} pagination={false} />
      </Card>
    </div>
  )
}
