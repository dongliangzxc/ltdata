import { useState } from 'react'
import {
  Card, Checkbox, Switch, Button, Table, Tag, Modal, Row, Col,
  Space, Typography, Input, message
} from 'antd'
import { PlayCircleOutlined, EyeOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUploadFiles, listCleanJobs, runCleanJob, previewCleanJob
} from '../../services/api'

const { Text } = Typography

const jobColumns = (onPreview: (id: number) => void) => [
  { title: 'ID', dataIndex: 'id', width: 60 },
  {
    title: '文件', dataIndex: 'file_ids', width: 120,
    render: (v: number[]) => v?.map(id => <Tag key={id}>文件#{id}</Tag>)
  },
  { title: '输入行', dataIndex: 'row_in', width: 80 },
  { title: '输出行', dataIndex: 'row_out', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => <Tag color={v === 'done' ? 'green' : v === 'error' ? 'red' : 'orange'}>{v}</Tag>
  },
  {
    title: '时间', dataIndex: 'created_at',
    render: (v: string) => new Date(v).toLocaleString('zh-CN')
  },
  {
    title: '操作', width: 80,
    render: (_: unknown, row: { id: number }) => (
      <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => onPreview(row.id)}>预览</Button>
    )
  },
]

const previewCols = [
  { title: '平台', dataIndex: 'platform', width: 90 },
  { title: '月份', dataIndex: 'month', width: 90 },
  { title: '品牌', dataIndex: 'brand_std', width: 110 },
  { title: '机型', dataIndex: 'model_std', width: 130 },
  { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true },
  { title: '销量', dataIndex: 'sales_qty', width: 80 },
  {
    title: '销售额', dataIndex: 'sales_amount', width: 110,
    render: (v: number) => v != null ? `¥${Number(v).toLocaleString()}` : '-'
  },
]

export default function CleanPage() {
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([])
  const [brandInput, setBrandInput] = useState('')
  const [dedup, setDedup] = useState(true)
  const [running, setRunning] = useState(false)
  const [previewJobId, setPreviewJobId] = useState<number | null>(null)
  const [previewPage, setPreviewPage] = useState(1)

  const { data: filesData } = useRequest(() => listUploadFiles().then(r => r.data))
  const { data: jobsData, refresh: refreshJobs } = useRequest(() => listCleanJobs().then(r => r.data))

  const { data: previewData, loading: previewLoading } = useRequest(
    () => previewCleanJob(previewJobId!, { page: previewPage, page_size: 20 }).then(r => r.data),
    { ready: previewJobId != null, refreshDeps: [previewJobId, previewPage] }
  )

  const handleRun = async () => {
    if (!selectedFileIds.length) { message.warning('请先选择文件'); return }
    setRunning(true)
    try {
      const filterBrands = brandInput.trim()
        ? brandInput.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean)
        : []
      await runCleanJob({ file_ids: selectedFileIds, rules: { filter_brands: filterBrands, dedup } })
      message.success('清洗完成')
      refreshJobs()
    } finally {
      setRunning(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="清洗配置">
        <Row gutter={24}>
          <Col span={12}>
            <Text strong>选择文件（可多选）</Text>
            <Checkbox.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}
              value={selectedFileIds}
              onChange={v => setSelectedFileIds(v as number[])}
            >
              {(filesData ?? []).map((f: { id: number; filename: string; platform: string; row_count: number }) => (
                <Checkbox key={f.id} value={f.id}>
                  <Space>
                    <Tag color="blue">{f.platform}</Tag>
                    {f.filename}
                    <Text type="secondary">({f.row_count} 条)</Text>
                  </Space>
                </Checkbox>
              ))}
            </Checkbox.Group>
          </Col>
          <Col span={12}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <div>
                <Text strong>品牌白名单（留空则保留全部）</Text>
                <Input
                  style={{ marginTop: 8 }}
                  placeholder="如：BOSE,JBL,EDIFIER（逗号或空格分隔）"
                  value={brandInput}
                  onChange={e => setBrandInput(e.target.value)}
                />
              </div>
              <div>
                <Space>
                  <Text strong>去重</Text>
                  <Switch checked={dedup} onChange={setDedup} />
                  <Text type="secondary">（同 item_id + 月份保留销量最大记录）</Text>
                </Space>
              </div>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleRun}
                loading={running}
                size="large"
              >
                开始清洗
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card title="清洗任务历史">
        <Table
          dataSource={jobsData ?? []}
          columns={jobColumns(id => { setPreviewJobId(id); setPreviewPage(1) })}
          rowKey="id"
          size="small"
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
          dataSource={previewData?.items ?? []}
          columns={previewCols}
          rowKey="id"
          size="small"
          loading={previewLoading}
          scroll={{ x: 800 }}
          pagination={{
            current: previewPage,
            pageSize: 20,
            total: previewData?.total ?? 0,
            onChange: setPreviewPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Modal>
    </Space>
  )
}
