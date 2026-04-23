import { useState } from 'react'
import {
  Card, Select, Input, Switch, Button, Table, Space, Typography, message, Row, Col
} from 'antd'
import { DownloadOutlined, ExportOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listCleanJobs, triggerExport, getDownloadUrl } from '../../services/api'

const { Text } = Typography

interface ExportFile {
  filename: string
  token: string
  rows: number
}

export default function ExportPage() {
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [filenamePrefix, setFilenamePrefix] = useState('Soundbar 7-8月已处理')
  const [splitByPlatform, setSplitByPlatform] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [exportedFiles, setExportedFiles] = useState<ExportFile[]>([])

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))

  const handleExport = async () => {
    if (!selectedJobId) { message.warning('请选择清洗任务'); return }
    setExporting(true)
    try {
      const res = await triggerExport({
        clean_job_id: selectedJobId,
        filename_prefix: filenamePrefix,
        split_by_platform: splitByPlatform,
      })
      setExportedFiles(res.data.files)
      message.success(`生成 ${res.data.files.length} 个文件，点击下载`)
    } finally {
      setExporting(false)
    }
  }

  const downloadCols = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    { title: '行数', dataIndex: 'rows', width: 90 },
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
                  onChange={setSelectedJobId}
                >
                  {doneJobs.map((j: { id: number; file_ids: number[]; row_out: number; created_at: string }) => (
                    <Select.Option key={j.id} value={j.id}>
                      任务 #{j.id} — 输出 {j.row_out} 条 — 文件{j.file_ids?.join(',')}
                      <Text type="secondary" style={{ marginLeft: 8 }}>
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
              <div>
                <Space>
                  <Text strong>按平台拆分文件</Text>
                  <Switch checked={splitByPlatform} onChange={setSplitByPlatform} />
                  <Text type="secondary">开启后每个平台生成独立文件</Text>
                </Space>
              </div>
              <Button
                type="primary"
                icon={<ExportOutlined />}
                onClick={handleExport}
                loading={exporting}
                size="large"
              >
                生成导出文件
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {exportedFiles.length > 0 && (
        <Card title="导出文件列表">
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
