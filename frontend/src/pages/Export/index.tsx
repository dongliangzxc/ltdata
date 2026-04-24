import { useState, useEffect } from 'react'
import {
  Card, Select, Input, Button, Table, Space, Typography, message,
  Row, Col, Alert, Statistic
} from 'antd'
import { DownloadOutlined, ExportOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listCleanJobs, triggerExport, getDownloadUrl, getMatchSummary } from '../../services/api'

const { Text } = Typography

interface ExportFile {
  filename: string
  token: string
  rows: number
  pending_rows: number
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
  const [exporting, setExporting] = useState(false)
  const [exportedFiles, setExportedFiles] = useState<ExportFile[]>([])
  const [matchSummary, setMatchSummary] = useState<MatchSummary | null>(null)

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))

  useEffect(() => {
    if (!selectedJobId) { setMatchSummary(null); return }
    getMatchSummary(selectedJobId)
      .then(r => setMatchSummary(r.data))
      .catch(() => setMatchSummary(null))
  }, [selectedJobId])

  const handleExport = async () => {
    if (!selectedJobId) { message.warning('请选择清洗任务'); return }
    if (!matchSummary) { message.warning('请先执行型号匹配'); return }
    setExporting(true)
    try {
      const res = await triggerExport({
        clean_job_id: selectedJobId,
        filename_prefix: filenamePrefix,
      })
      setExportedFiles(res.data.files)
      const f = res.data.files[0]
      message.success(`导出成功，已匹配 ${f.rows} 条，待确认 ${f.pending_rows} 条`)
    } finally {
      setExporting(false)
    }
  }

  const downloadCols = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    { title: '已匹配行数', dataIndex: 'rows', width: 110 },
    { title: '待确认行数', dataIndex: 'pending_rows', width: 110 },
    {
      title: '操作', width: 100,
      render: (_: unknown, row: ExportFile) => (
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          size="small"
          href={getDownloadUrl(row.token)}
          target="_blank"
        >
          下载
        </Button>
      )
    }
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
                  onChange={v => { setSelectedJobId(v); setExportedFiles([]) }}
                >
                  {doneJobs.map((j: { id: number; file_ids: number[]; row_out: number; created_at: string }) => (
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
                onClick={handleExport}
                loading={exporting}
                size="large"
                disabled={!matchSummary || readyMatched === 0}
              >
                生成导出文件
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

      {exportedFiles.length > 0 && (
        <Card title="导出文件">
          <Table
            dataSource={exportedFiles}
            columns={downloadCols}
            rowKey="token"
            size="small"
            pagination={false}
          />
        </Card>
      )}
    </Space>
  )
}
