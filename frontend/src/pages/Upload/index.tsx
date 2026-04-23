import { useState } from 'react'
import {
  Card, Upload, Table, Tag, Button, Popconfirm,
  message, Space, Typography
} from 'antd'
import { InboxOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { uploadFile, listUploadFiles, deleteUploadFile } from '../../services/api'

const { Text } = Typography

const PLATFORM_LABEL: Record<string, string> = { JD: '京东', TM: '天猫', TB: '淘宝' }

const previewColumns = [
  { title: '平台', dataIndex: 'platform', width: 100, ellipsis: true },
  { title: '月份', dataIndex: 'month', width: 90 },
  { title: '品牌', dataIndex: 'brand_std', width: 100 },
  { title: '机型', dataIndex: 'model_std', width: 120 },
  { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true },
  { title: '销量', dataIndex: 'sales_qty', width: 80 },
  { title: '销售额', dataIndex: 'sales_amount', width: 110 },
  { title: '价格', dataIndex: 'price', width: 90 },
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
    render: (v: string) => <Tag color={v === 'done' ? 'green' : 'orange'}>{v}</Tag>
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
  const [previewInfo, setPreviewInfo] = useState<{ filename: string; row_count: number; platform: string; month_range: string } | null>(null)
  const Dragger = Upload.Dragger

  const { data: filesData, loading: filesLoading, refresh: refreshFiles } = useRequest(
    () => listUploadFiles().then(r => r.data),
    { refreshDeps: [] }
  )

  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await uploadFile(formData)
      const { preview, filename, row_count, platform, month_range } = res.data
      setPreviewData(preview)
      setPreviewInfo({ filename, row_count, platform, month_range })
      message.success(`上传成功，共 ${row_count} 条数据`)
      refreshFiles()
    } catch {
      // error handled by interceptor
    }
    return false // 阻止 antd 默认上传
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
          accept=".xlsx,.xls"
          multiple={false}
          beforeUpload={handleUpload}
          showUploadList={false}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 Excel 文件至此上传</p>
          <p className="ant-upload-hint">支持 .xlsx / .xls 格式，兼容京东/天猫/淘宝原始数据格式</p>
        </Dragger>
      </Card>

      {previewInfo && (
        <Card
          title={`数据预览：${previewInfo.filename}`}
          extra={
            <Space>
              <Tag color="blue">{PLATFORM_LABEL[previewInfo.platform] ?? previewInfo.platform}</Tag>
              <Tag color="geekblue">{previewInfo.month_range}</Tag>
              <Text type="secondary">共 {previewInfo.row_count} 条，展示前 50 行</Text>
            </Space>
          }
        >
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
