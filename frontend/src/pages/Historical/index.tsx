import { useState, useEffect } from 'react'
import {
  Tabs, Table, Button, Upload, Space, Select, Tag, Popconfirm, message
} from 'antd'
import { InboxOutlined, DeleteOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import {
  importHistoricalMappings,
  listHistoricalBatches,
  listHistoricalMappings,
  deleteHistoricalMapping,
  deleteHistoricalBatch,
} from '../../services/api'

const { Dragger } = Upload

// ─── Tab 1: 导入历史对照表 ──────────────────────────────────────────
function ImportTab() {
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<{
    success: number; errors: { row: number; reason: string }[]; import_batch: string
  } | null>(null)
  const [batches, setBatches] = useState<{ batch: string; count: number }[]>([])

  const loadBatches = async () => {
    const res = await listHistoricalBatches()
    setBatches(res.data)
  }

  useEffect(() => { loadBatches() }, [])

  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    setUploading(true)
    try {
      const res = await importHistoricalMappings(formData)
      setResult(res.data)
      message.success(`导入完成：成功 ${res.data.success} 条`)
      loadBatches()
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleDeleteBatch = async (batch: string) => {
    await deleteHistoricalBatch(batch)
    message.success('批次已删除')
    loadBatches()
    setResult(null)
  }

  const uploadProps: UploadProps = {
    multiple: false,
    accept: '.xlsx,.xls',
    beforeUpload: (file) => { handleUpload(file); return false },
    showUploadList: false,
    disabled: uploading,
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Dragger {...uploadProps}>
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p>点击或拖拽 Excel 文件到此处导入历史对照表</p>
        <p style={{ color: '#888', fontSize: 12 }}>必需列：platform / item_id / model_code</p>
      </Dragger>

      {result && (
        <div>
          <p>
            <b>批次：</b>{result.import_batch}&nbsp;&nbsp;
            <b>成功：</b>{result.success} 条&nbsp;&nbsp;
            <b>失败：</b>{result.errors.length} 条
          </p>
          {result.errors.length > 0 && (
            <Table
              size="small"
              dataSource={result.errors}
              rowKey="row"
              pagination={false}
              columns={[
                { title: '行号', dataIndex: 'row', key: 'row', width: 80 },
                { title: '失败原因', dataIndex: 'reason', key: 'reason' },
              ]}
              title={() => `失败明细（${result.errors.length} 条）`}
            />
          )}
        </div>
      )}

      <Table
        title={() => '历史导入批次'}
        dataSource={batches}
        rowKey={(r) => r.batch}
        pagination={false}
        columns={[
          { title: '批次名称', dataIndex: 'batch', key: 'batch' },
          { title: '条数', dataIndex: 'count', key: 'count', width: 80 },
          {
            title: '操作', key: 'action', width: 120,
            render: (_: unknown, record: { batch: string; count: number }) => (
              <Popconfirm
                title="确认删除该批次所有映射？"
                onConfirm={() => handleDeleteBatch(record.batch)}
              >
                <Button type="link" danger size="small" icon={<DeleteOutlined />}>删除批次</Button>
              </Popconfirm>
            ),
          },
        ]}
      />
    </Space>
  )
}

// ─── Tab 2: 映射管理 ────────────────────────────────────────────
function MappingTab() {
  const [data, setData] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 20
  const [platform, setPlatform] = useState<string | undefined>()
  const [batch, setBatch] = useState<string | undefined>()
  const [batches, setBatches] = useState<{ batch: string; count: number }[]>([])
  const [loading, setLoading] = useState(false)

  const loadBatches = async () => {
    const res = await listHistoricalBatches()
    setBatches(res.data)
  }

  const load = async () => {
    setLoading(true)
    try {
      const res = await listHistoricalMappings({
        platform, import_batch: batch, page, page_size: PAGE_SIZE,
      })
      setData(res.data.items)
      setTotal(res.data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadBatches() }, [])
  useEffect(() => { load() }, [platform, batch, page])

  const handleDelete = async (id: number) => {
    await deleteHistoricalMapping(id)
    message.success('已删除')
    load()
  }

  const columns = [
    {
      title: '平台', dataIndex: 'platform', key: 'platform', width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    { title: '商品ID', dataIndex: 'item_id', key: 'item_id' },
    { title: '品牌', dataIndex: 'brand_code', key: 'brand_code', width: 100 },
    { title: '型号', dataIndex: 'model_code', key: 'model_code', width: 160 },
    { title: '导入批次', dataIndex: 'import_batch', key: 'import_batch' },
    {
      title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 160,
      render: (v: string) => v?.slice(0, 19),
    },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: any) => (
        <Popconfirm title="确认删除此条映射？" onConfirm={() => handleDelete(record.id)}>
          <Button type="link" danger size="small">删除</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Space>
        <Select
          placeholder="平台"
          allowClear
          style={{ width: 120 }}
          options={['jd', 'tmall', 'taobao', 'suning'].map(p => ({ value: p, label: p }))}
          onChange={v => { setPlatform(v); setPage(1) }}
        />
        <Select
          placeholder="导入批次"
          allowClear
          style={{ width: 220 }}
          options={batches.map(b => ({ value: b.batch, label: `${b.batch} (${b.count}条)` }))}
          onChange={v => { setBatch(v); setPage(1) }}
        />
      </Space>
      <Table
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showTotal: t => `共 ${t} 条`,
        }}
      />
    </Space>
  )
}

// ─── 页面主体 ────────────────────────────────────────────────────
export default function HistoricalPage() {
  return (
    <Tabs
      items={[
        { key: 'import',   label: '导入历史对照表', children: <ImportTab /> },
        { key: 'mappings', label: '映射管理',       children: <MappingTab /> },
      ]}
    />
  )
}
