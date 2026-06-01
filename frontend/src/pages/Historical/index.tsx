import { useState, useEffect } from 'react'
import {
  Tabs, Table, Button, Upload, Space, Select, Tag, Popconfirm, message, Input, Card, Statistic, Alert
} from 'antd'
import { InboxOutlined, DeleteOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  importHistoricalMappings,
  listHistoricalBatches,
  listHistoricalMappings,
  deleteHistoricalMapping,
  deleteHistoricalBatch,
  type HistoricalBatchItem,
  type HistoricalImportResult,
  type HistoricalMappingItem,
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

const { Dragger } = Upload
const PAGE_SIZE = 20

function formatDateTime(value: string | null | undefined) {
  return value ? value.slice(0, 19) : '-'
}

// ─── Tab 1: 导入历史确认结果 ─────────────────────────────────────
function ImportTab() {
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<HistoricalImportResult | null>(null)
  const [batches, setBatches] = useState<HistoricalBatchItem[]>([])

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
      message.success(`导入完成：成功 ${res.data.success} 条，新增 ${res.data.created} 条，更新 ${res.data.updated} 条`)
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
        <p>{uploading ? '正在导入历史库数据，请不要刷新页面' : '点击或拖拽 Excel 文件到此处导入历史库数据'}</p>
        <p style={{ color: '#888', fontSize: 12 }}>
          必填列：商场或渠道 / 标题 / 年 / 月；推荐列：周 / 报告类型 / 品类 / 品牌 / 型号 / 品类码 / 品牌码 / 型号码 / 销额 / 销量 / 单价 / 网址。型号可为空，后续可补充。
        </p>
      </Dragger>

      {uploading && (
        <Alert type="info" showIcon message="导入处理中" description="大 Excel 需要解析和写入较多数据，完成后会显示成功、失败明细和导入批次。" />
      )}

      {result && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            <Card size="small"><Statistic title="批次" value={result.import_batch} /></Card>
            <Card size="small"><Statistic title="成功" value={result.success} suffix="条" /></Card>
            <Card size="small"><Statistic title="新增" value={result.created} suffix="条" /></Card>
            <Card size="small"><Statistic title="更新" value={result.updated} suffix="条" /></Card>
            <Card size="small"><Statistic title="失败" value={result.errors.length} suffix="条" /></Card>
          </Space>
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
        </Space>
      )}

      <Table<HistoricalBatchItem>
        title={() => '历史导入批次'}
        dataSource={batches}
        rowKey={(r) => r.batch}
        pagination={false}
        columns={[
          { title: '批次名称', dataIndex: 'batch', key: 'batch' },
          { title: '条数', dataIndex: 'count', key: 'count', width: 80 },
          { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180, render: formatDateTime },
          {
            title: '操作', key: 'action', width: 120,
            render: (_: unknown, record: HistoricalBatchItem) => (
              <Popconfirm
                title="确认删除该批次所有历史结果？"
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

// ─── Tab 2: 历史结果管理 ────────────────────────────────────────
function MappingTab() {
  const [data, setData] = useState<HistoricalMappingItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [platform, setPlatform] = useState<string | undefined>()
  const [batch, setBatch] = useState<string | undefined>()
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [month, setMonth] = useState<string>()
  const [modelKeyword, setModelKeyword] = useState('')
  const [itemKeyword, setItemKeyword] = useState('')
  const [batches, setBatches] = useState<HistoricalBatchItem[]>([])
  const [loading, setLoading] = useState(false)
  const { options: categoryOptions } = useCategoryOptions()

  const loadBatches = async () => {
    const res = await listHistoricalBatches()
    setBatches(res.data)
  }

  const load = async () => {
    setLoading(true)
    try {
      const res = await listHistoricalMappings({
        platform,
        import_batch: batch,
        category_code: categoryCode,
        month,
        model_keyword: modelKeyword || undefined,
        item_keyword: itemKeyword || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      setData(res.data.items)
      setTotal(res.data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadBatches() }, [])
  useEffect(() => { load() }, [platform, batch, categoryCode, month, modelKeyword, itemKeyword, page])

  const resetPage = () => setPage(1)

  const handleDelete = async (id: number) => {
    await deleteHistoricalMapping(id)
    message.success('已删除')
    load()
  }

  const columns: ColumnsType<HistoricalMappingItem> = [
    {
      title: '平台', dataIndex: 'platform', key: 'platform', width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    { title: '商品ID', dataIndex: 'item_id', key: 'item_id', width: 150, render: (v) => v || '-' },
    { title: '标题', dataIndex: 'item_name', key: 'item_name', ellipsis: true, width: 260 },
    { title: '品牌', dataIndex: 'brand_raw', key: 'brand_raw', width: 120, render: (v, r) => v || r.brand_code_raw || '-' },
    { title: '确认型号', dataIndex: 'model_text', key: 'model_text', width: 140, render: (v) => v || <Tag color="warning">待补</Tag> },
    {
      title: '标准型号', key: 'standard_model', width: 170,
      render: (_, r) => r.model_code ? (r.standard_model_name ? `${r.model_code} / ${r.standard_model_name}` : r.model_code) : <Tag color="warning">待补</Tag>,
    },
    { title: '品类', dataIndex: 'category_code', key: 'category_code', width: 120, render: (v, r) => v || r.category_name_raw || '-' },
    { title: '年月', dataIndex: 'month', key: 'month', width: 100 },
    { title: '周', dataIndex: 'week', key: 'week', width: 80, render: (v) => v || '-' },
    { title: '销量', dataIndex: 'sales_qty', key: 'sales_qty', width: 90, render: (v) => v ?? '-' },
    { title: '单价', dataIndex: 'price', key: 'price', width: 90, render: (v) => v ?? '-' },
    {
      title: '网址', dataIndex: 'item_url', key: 'item_url', width: 80,
      render: (v: string | null) => v ? <a href={v} target="_blank" rel="noreferrer">打开</a> : '-',
    },
    { title: '导入批次', dataIndex: 'import_batch', key: 'import_batch', width: 180, render: (v) => v || '-' },
    { title: '匹配键', dataIndex: 'match_key_type', key: 'match_key_type', width: 90 },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180, render: formatDateTime },
    {
      title: '操作', key: 'action', width: 80, fixed: 'right',
      render: (_: unknown, record) => (
        <Popconfirm title="确认删除此条历史结果？" onConfirm={() => handleDelete(record.id)}>
          <Button type="link" danger size="small">删除</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Space wrap>
        <Select
          placeholder="平台"
          allowClear
          style={{ width: 120 }}
          options={['jd', 'tmall', 'taobao', 'suning'].map(p => ({ value: p, label: p }))}
          onChange={v => { setPlatform(v); resetPage() }}
        />
        <Select
          placeholder="导入批次"
          allowClear
          showSearch
          style={{ width: 220 }}
          options={batches.map(b => ({ value: b.batch, label: `${b.batch} (${b.count}条)` }))}
          onChange={v => { setBatch(v); resetPage() }}
        />
        <Select
          placeholder="品类"
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 160 }}
          options={categoryOptions}
          onChange={v => { setCategoryCode(v); resetPage() }}
        />
        <Input
          placeholder="月份 YYYY-MM"
          allowClear
          style={{ width: 140 }}
          value={month}
          onChange={e => { setMonth(e.target.value || undefined); resetPage() }}
        />
        <Input.Search
          placeholder="型号关键词"
          allowClear
          style={{ width: 180 }}
          value={modelKeyword}
          onChange={e => setModelKeyword(e.target.value)}
          onSearch={() => resetPage()}
        />
        <Input.Search
          placeholder="标题关键词"
          allowClear
          style={{ width: 220 }}
          value={itemKeyword}
          onChange={e => setItemKeyword(e.target.value)}
          onSearch={() => resetPage()}
        />
      </Space>
      <Table<HistoricalMappingItem>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        scroll={{ x: 1900 }}
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
        { key: 'import',   label: '导入历史确认结果', children: <ImportTab /> },
        { key: 'mappings', label: '历史结果管理',       children: <MappingTab /> },
      ]}
    />
  )
}
