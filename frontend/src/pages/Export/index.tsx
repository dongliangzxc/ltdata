import { useState, useEffect, useRef } from 'react'
import {
  Card, Select, Input, Button, Table, Space, Typography, message,
  Row, Col, Alert, Statistic, Tag, Tooltip
} from 'antd'
import { ExportOutlined, DownloadOutlined, ReloadOutlined, LoadingOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listCleanJobs, triggerExport, getDownloadUrl, getMatchSummary, listExportJobs } from '../../services/api'

const { Text } = Typography

type ExportJobItem = {
  id: number
  clean_job_id: number
  filename_prefix: string
  status: 'pending' | 'running' | 'done' | 'error'
  filename: string | null
  token: string | null
  rows: number | null
  pending_rows: number | null
  error_msg: string | null
  created_at: string
}

type MatchSummary = {
  total: number
  matched: number
  pending: number
  confirmed: number
  excluded: number
}

export default function ExportPage() {
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [filenamePrefix, setFilenamePrefix] = useState('已处理数据')
  const [triggering, setTriggering] = useState(false)
  const [matchSummary, setMatchSummary] = useState<MatchSummary | null>(null)
  const [exportJobs, setExportJobs] = useState<ExportJobItem[]>([])
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))

  // 加载导出历史（全部）
  const loadExportJobs = () => {
    listExportJobs().then(r => setExportJobs(r.data.data ?? [])).catch(() => {})
  }

  useEffect(() => {
    loadExportJobs()
  }, [])

  // 有 pending/running 的任务时自动轮询
  useEffect(() => {
    const hasPending = exportJobs.some(j => j.status === 'pending' || j.status === 'running')
    if (hasPending) {
      if (!pollTimerRef.current) {
        pollTimerRef.current = setInterval(loadExportJobs, 2000)
      }
    } else {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [exportJobs])

  useEffect(() => {
    if (!selectedJobId) { setMatchSummary(null); return }
    getMatchSummary(selectedJobId)
      .then(r => setMatchSummary(r.data))
      .catch(() => setMatchSummary(null))
  }, [selectedJobId])

  const handleTrigger = async () => {
    if (!selectedJobId) { message.warning('请选择清洗任务'); return }
    if (!matchSummary) { message.warning('请先执行型号匹配'); return }
    setTriggering(true)
    try {
      await triggerExport({ clean_job_id: selectedJobId, filename_prefix: filenamePrefix })
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
      done:    { color: 'success',    label: '已完成' },
      error:   { color: 'error',      label: '失败' },
    }
    const { color, label } = map[status] ?? { color: 'default', label: status }
    return <Tag color={color}>{status === 'running' ? <><LoadingOutlined /> {label}</> : label}</Tag>
  }

  const exportCols = [
    {
      title: '清洗任务', dataIndex: 'clean_job_id', width: 90,
      render: (v: number) => `#${v}`
    },
    { title: '文件名前缀', dataIndex: 'filename_prefix', width: 150, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: ExportJobItem['status']) => statusTag(v)
    },
    { title: '已匹配行', dataIndex: 'rows', width: 90, render: (v: number | null) => v ?? '-' },
    { title: '待确认行', dataIndex: 'pending_rows', width: 90, render: (v: number | null) => v ?? '-' },
    {
      title: '提交时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN')
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
        return <Text type="secondary" style={{ fontSize: 12 }}>等待中…</Text>
      }
    },
  ]

  const doneJobs = (jobsData ?? []).filter((j: { status: string }) => j.status === 'done')
  const readyMatched = matchSummary ? matchSummary.matched + matchSummary.confirmed : 0

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="导出配置">
        <Row gutter={24}>
          <Col span={12}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <div>
                <Text strong>选择清洗任务</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  placeholder="选择已完成的清洗任务"
                  value={selectedJobId}
                  onChange={v => { setSelectedJobId(v); setMatchSummary(null) }}
                >
                  {doneJobs.map((j: { id: number; row_out: number; created_at: string }) => (
                    <Select.Option key={j.id} value={j.id}>
                      任务 #{j.id} — 输出 {j.row_out} 条 —
                      <Text type="secondary" style={{ marginLeft: 4 }}>
                        {new Date(j.created_at).toLocaleDateString('zh-CN')}
                      </Text>
                    </Select.Option>
                  ))}
                </Select>
              </div>
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
                disabled={!matchSummary || readyMatched === 0}
              >
                提交导出任务
              </Button>
            </Space>
          </Col>
          <Col span={12}>
            {selectedJobId && matchSummary && (
              <Card size="small" title="匹配状态">
                <Row gutter={12}>
                  <Col span={8}><Statistic title="已匹配" value={matchSummary.matched} valueStyle={{ color: '#3f8600', fontSize: 18 }} /></Col>
                  <Col span={8}><Statistic title="已确认" value={matchSummary.confirmed} valueStyle={{ color: '#1677ff', fontSize: 18 }} /></Col>
                  <Col span={8}><Statistic title="待确认" value={matchSummary.pending} valueStyle={{ color: '#d46b08', fontSize: 18 }} /></Col>
                </Row>
                {matchSummary.pending > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 12 }}
                    message={`还有 ${matchSummary.pending} 条待确认，可先导出已匹配部分，未确认的会进入"待确认" Sheet`}
                  />
                )}
              </Card>
            )}
            {selectedJobId && !matchSummary && (
              <Alert type="info" showIcon message="该任务尚未执行型号匹配，请先前往「匹配确认」页面完成匹配" />
            )}
          </Col>
        </Row>
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
              scroll={{ x: 750 }}
            />
          )
        }
      </Card>
    </Space>
  )
}
