import { useMemo, useState, useEffect, useRef } from 'react'
import {
  Card, Select, Input, Button, Table, Space, Typography, message,
  Row, Col, Alert, Tag, Tooltip
} from 'antd'
import { ExportOutlined, DownloadOutlined, ReloadOutlined, LoadingOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  triggerExport,
  getDownloadUrl,
  listExportJobs,
  getExportFilters,
  type ExportFilterOption,
  type ExportJobItem,
} from '../../services/api'

const { Text } = Typography

const platformLabelMap: Record<string, string> = {
  jd: '京东',
  tmall: '天猫',
  taobao: '淘宝',
  douyin: '抖音',
}

const emptyFilterOptions: ExportFilterOption = {
  months: [],
  platforms: [],
  categories: [],
}

const formatPlatform = (value?: string | null) => value ? (platformLabelMap[value] ?? value) : '-'

export default function ExportPage() {
  const [selectedMonths, setSelectedMonths] = useState<number[]>([])
  const [selectedCategoryCode, setSelectedCategoryCode] = useState<string | undefined>(undefined)
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([])
  const [filenamePrefix, setFilenamePrefix] = useState('已处理数据')
  const [triggering, setTriggering] = useState(false)
  const [exportJobs, setExportJobs] = useState<ExportJobItem[]>([])
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: filterData, loading: filterLoading } = useRequest<ExportFilterOption, []>(
    () => getExportFilters().then(r => r.data)
  )
  const filterOptions = filterData ?? emptyFilterOptions

  const categoryLabelMap = useMemo(
    () => filterOptions.categories.reduce<Record<string, string>>((acc, category) => {
      acc[category.code] = category.name
      return acc
    }, {}),
    [filterOptions.categories]
  )

  const platformOptions = useMemo(
    () => filterOptions.platforms.map(platform => ({ value: platform, label: formatPlatform(platform) })),
    [filterOptions.platforms]
  )

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

  const statusTag = (status: ExportJobItem['status']) => {
    const map: Record<string, { color: string; label: string }> = {
      pending: { color: 'default', label: '排队中' },
      running: { color: 'processing', label: '生成中' },
      done: { color: 'success', label: '已完成' },
      error: { color: 'error', label: '失败' },
    }
    const { color, label } = map[status] ?? { color: 'default', label: status }
    return <Tag color={color}>{status === 'running' ? <><LoadingOutlined /> {label}</> : label}</Tag>
  }

  const formatExportScope = (row: ExportJobItem) => {
    if (row.clean_job_id != null) return `清洗任务 #${row.clean_job_id}`
    const months = row.months?.join('、') || '-'
    const category = categoryLabelMap[row.category_code ?? ''] ?? row.category_code ?? '-'
    const platforms = row.platforms?.map(formatPlatform).join('、') || '-'
    return `${months}｜${category}｜${platforms}`
  }

  const exportCols = [
    {
      title: '导出范围', dataIndex: 'clean_job_id', width: 220, ellipsis: true,
      render: (_: unknown, row: ExportJobItem) => formatExportScope(row),
    },
    { title: '文件名前缀', dataIndex: 'filename_prefix', width: 150, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: ExportJobItem['status']) => statusTag(v),
    },
    { title: '已匹配行', dataIndex: 'rows', width: 90, render: (v: number | null) => v ?? '-' },
    { title: '待确认行', dataIndex: 'pending_rows', width: 90, render: (v: number | null) => v ?? '-' },
    {
      title: '提交时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => v || '-',
    },
    {
      title: '操作', width: 100, fixed: 'right' as const,
      render: (_: unknown, row: ExportJobItem) => {
        if (row.status === 'done' && row.token) {
          return (
            <Button
              type="primary"
              size="small"
              icon={<DownloadOutlined />}
              href={getDownloadUrl(row.token)}
              target="_blank"
            >
              下载
            </Button>
          )
        }
        if (row.status === 'error') {
          return (
            <Tooltip title={row.error_msg}>
              <Text type="danger" style={{ fontSize: 12 }}>查看错误</Text>
            </Tooltip>
          )
        }
        return <Text type="secondary" style={{ fontSize: 12 }}>等待中...</Text>
      },
    },
  ]

  const hasFilterOptions = filterOptions.months.length > 0
    || filterOptions.categories.length > 0
    || filterOptions.platforms.length > 0

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="导出配置">
        {!filterLoading && !hasFilterOptions && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="暂无可导出的清洗结果"
          />
        )}

        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Text strong>月度</Text>
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择月度"
              loading={filterLoading}
              value={selectedMonths}
              onChange={setSelectedMonths}
              options={filterOptions.months.map(month => ({ value: month, label: String(month) }))}
            />
          </Col>
          <Col span={8}>
            <Text strong>品类</Text>
            <Select
              showSearch
              allowClear
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择品类"
              loading={filterLoading}
              value={selectedCategoryCode}
              onChange={setSelectedCategoryCode}
              optionFilterProp="label"
              options={filterOptions.categories.map(category => ({ value: category.code, label: category.name }))}
            />
          </Col>
          <Col span={8}>
            <Text strong>平台</Text>
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择平台"
              loading={filterLoading}
              value={selectedPlatforms}
              onChange={setSelectedPlatforms}
              options={platformOptions}
            />
          </Col>
        </Row>

        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <Text strong>文件名前缀</Text>
            <Input
              style={{ marginTop: 8 }}
              value={filenamePrefix}
              onChange={e => setFilenamePrefix(e.target.value)}
              placeholder="如：Soundbar 7-8月已处理"
            />
          </div>
          <Button
            type="primary"
            icon={<ExportOutlined />}
            onClick={handleTrigger}
            loading={triggering}
            size="large"
            disabled={selectedMonths.length === 0 || !selectedCategoryCode || selectedPlatforms.length === 0}
          >
            提交导出任务
          </Button>
        </Space>
      </Card>

      <Card
        title="导出历史"
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={loadExportJobs}>刷新</Button>
        }
      >
        {exportJobs.length === 0
          ? <Text type="secondary">暂无导出记录</Text>
          : (
            <Table
              dataSource={exportJobs}
              columns={exportCols}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: 820 }}
            />
          )
        }
      </Card>
    </Space>
  )
}
