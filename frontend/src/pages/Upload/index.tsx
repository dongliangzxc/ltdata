import { useState } from 'react'
import {
  Card, Upload, Table, Tag, Button, Popconfirm,
  message, Space, Typography, Spin, Alert
} from 'antd'
import { InboxOutlined, DeleteOutlined, ReloadOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { uploadFile, listUploadFiles, deleteUploadFile } from '../../services/api'

const { Text } = Typography

const PLATFORM_LABEL: Record<string, string> = { JD: '京东', TM: '天猫', TB: '淘宝' }

const renderVal = (v: unknown) => (v == null || v === '' ? <Text type="secondary">-</Text> : String(v))

const previewColumns = [
  { title: '平台', dataIndex: 'platform', width: 100, ellipsis: true, render: renderVal },
  { title: '月份', dataIndex: 'month', width: 90, render: renderVal },
  { title: '品牌', dataIndex: 'brand_std', width: 100, render: renderVal },
  { title: '机型', dataIndex: 'model_std', width: 120, render: renderVal },
  { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true, render: renderVal },
  { title: '销量', dataIndex: 'sales_qty', width: 80, render: renderVal },
  {
    title: '销售额', dataIndex: 'sales_amount', width: 110,
    render: (v: number) => v != null ? `¥${Number(v).toLocaleString()}` : <Text type="secondary">-</Text>
  },
  {
    title: '价格', dataIndex: 'price', width: 90,
    render: (v: number) => v != null ? `¥${Number(v).toFixed(2)}` : <Text type="secondary">-</Text>
  },
]

const historyColumns = (onDelete: (id: number) => void) => [
  { title: 'ID', dataIndex: 'id', width: 60 },
  { title: '文件名', dataIndex: 'filename', ellipsis: true },
  {
    title: '平台', dataIndex: 'platform', width: 80,
    render: (v: string) => <Tag color="blue">{PLATFORM_LABEL[v] ?? v}</Tag>
  },
  { title: '月份范围', dataIndex: 'month_range', width: 130 },
  { title: '数据量', dataIndex: 'row_count', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => <Tag color={v === 'done' ? 'green' : 'orange'}>{v === 'done' ? '已完成' : v}</Tag>
  },
  {
    title: '上传时间', dataIndex: 'uploaded_at', width: 170,
    render: (v: string) => new Date(v).toLocaleString('zh-CN'),
  },
  {
    title: '操作', width: 80,
    render: (_: unknown, row: { id: number }) => (
      <Popconfirm title="确认删除该文件记录？" onConfirm={() => onDelete(row.id)} okText="删除" cancelText="取消">
        <Button type="link" danger icon={<DeleteOutlined />} size="small">删除</Button>
      </Popconfirm>
    ),
  },
]

export default function UploadPage() {
  const [previewData, setPreviewData] = useState<Record<string, unknown>[]>([])
  const [previewInfo, setPreviewInfo] = useState<{
    filename: string
    row_count: number
    platform: string
    month_range: string
    inserted: number
    skipped: number
  } | null>(null)
  const [uploading, setUploading] = useState(false)
  const Dragger = Upload.Dragger

  const { data: filesData, loading: filesLoading, refresh: refreshFiles } = useRequest(
    () => listUploadFiles().then(r => r.data),
    { refreshDeps: [] }
  )

  const handleUpload = async (file: File) => {
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await uploadFile(formData)
      const { preview, filename, row_count, platform, month_range, inserted, skipped } = res.data
      setPreviewData(preview)
      setPreviewInfo({ filename, row_count, platform, month_range, inserted: inserted ?? row_count, skipped: skipped ?? 0 })
      message.success(`上传成功，共解析 ${row_count} 条数据`)
      refreshFiles()
    } catch {
      // error handled by interceptor
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleDelete = async (id: number) => {
    await deleteUploadFile(id)
    message.success('已删除')
    refreshFiles()
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Dragger
          accept=".xlsx,.xls,.csv"
          multiple={false}
          beforeUpload={handleUpload}
          showUploadList={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            {uploading ? <Spin /> : <InboxOutlined />}
          </p>
          <p className="ant-upload-text">
            {uploading ? '正在上传并解析中...' : '点击或拖拽 Excel / CSV 文件至此上传'}
          </p>
          <p className="ant-upload-hint">支持 .xlsx / .xls / .csv 格式，兼容京东 / 天猫 / 淘宝原始数据格式</p>
        </Dragger>
      </Card>

      {previewInfo && (
        <Card
          title={
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              {`数据预览：${previewInfo.filename}`}
            </Space>
          }
          extra={
            <Space>
              <Tag color="blue">{PLATFORM_LABEL[previewInfo.platform] ?? previewInfo.platform}</Tag>
              <Tag color="geekblue">{previewInfo.month_range}</Tag>
              <Text type="secondary">共 {previewInfo.row_count} 条，展示前 50 行</Text>
            </Space>
          }
        >
          <Alert
            type="info"
            showIcon
            message={`文件已成功入库，写入 ${previewInfo.inserted} 条数据${previewInfo.skipped > 0 ? `，跳过重复 ${previewInfo.skipped} 条` : ''}。可前往「原始数据」页面查看完整数据，或前往「数据清洗」进行处理。`}
            style={{ marginBottom: 12 }}
          />
          <Table
            dataSource={previewData}
            columns={previewColumns}
            rowKey={(_r, i) => String(i)}
            size="small"
            scroll={{ x: 900 }}
            pagination={false}
          />
        </Card>
      )}

      <Card
        title="上传历史"
        extra={
          <Button icon={<ReloadOutlined />} onClick={refreshFiles} loading={filesLoading}>刷新</Button>
        }
      >
        <Table
          dataSource={filesData ?? []}
          columns={historyColumns(handleDelete)}
          rowKey="id"
          size="small"
          loading={filesLoading}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </Space>
  )
}
