import { useState } from 'react'
import {
  Card, Table, Button, Input, Select, Space, Typography,
  Modal, Form, InputNumber, Upload, message, Popconfirm, Tag,
} from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined, LinkOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUrlMappings, createUrlMapping, updateUrlMapping,
  deleteUrlMapping, importUrlMappings, listModels,
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

const { Text } = Typography

type UrlMapping = {
  id: number
  platform: string
  item_id: string
  item_url: string | null
  model_id: number
  price: number | null
  brand_code: string | null
  model_code: string | null
  brand_name: string | null
  model_name: string | null
}

type ModelOption = {
  id: number
  brand_code: string
  model_code: string
  brand_name: string | null
  model_name: string | null
  category_code: string | null
}

const PLATFORM_OPTIONS = [
  { value: 'jd', label: '京东 (JD)' },
  { value: 'tmall', label: '天猫 (TMALL)' },
  { value: 'taobao', label: '淘宝 (TAOBAO)' },
  { value: 'suning', label: '苏宁 (SUNING)' },
]

function buildUrl(platform: string, itemId: string): string | null {
  switch (platform) {
    case 'jd':     return `https://item.jd.com/${itemId}.html`
    case 'tmall':  return `https://detail.tmall.com/item.htm?id=${itemId}`
    case 'taobao': return `https://item.taobao.com/item.htm?id=${itemId}`
    default:       return null
  }
}

export default function UrlMappingsPage() {
  const [keyword, setKeyword] = useState('')
  const [platform, setPlatform] = useState<string | undefined>()
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [importing, setImporting] = useState(false)
  const [modalCategoryCode, setModalCategoryCode] = useState<string | undefined>()

  const { options: categoryOptions } = useCategoryOptions()

  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 500 }).then(r => r.data)
  )
  const modelOptions: ModelOption[] = modelsData?.items ?? []

  const { data, loading, refresh } = useRequest(
    () => listUrlMappings({ keyword: keyword || undefined, platform: platform || undefined, category_code: categoryCode || undefined, page, page_size: 20 }).then(r => r.data),
    { refreshDeps: [keyword, platform, categoryCode, page] }
  )

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    setModalCategoryCode(undefined)
    setModalOpen(true)
  }

  const openEdit = (record: UrlMapping) => {
    setEditingId(record.id)
    form.setFieldsValue({
      platform: record.platform,
      item_id: record.item_id,
      item_url: record.item_url,
      model_id: record.model_id,
      price: record.price,
    })
    setModalCategoryCode(undefined)
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editingId) {
        await updateUrlMapping(editingId, values)
        message.success('已更新')
      } else {
        await createUrlMapping(values)
        message.success('已新增')
      }
      setModalOpen(false)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    await deleteUrlMapping(id)
    message.success('已删除')
    refresh()
  }

  const handleImport = async (file: File) => {
    setImporting(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importUrlMappings(fd)
      const { imported, skipped, errors } = res.data
      message.success(`导入完成：写入 ${imported} 条，跳过 ${skipped} 条`)
      if (errors?.length) {
        message.warning(`部分行有问题：${errors.slice(0, 3).join('；')}`, 8)
      }
      refresh()
    } finally {
      setImporting(false)
    }
    return false  // prevent default upload
  }

  const filteredModelOptions = modalCategoryCode
    ? modelOptions.filter(m => m.category_code === modalCategoryCode)
    : modelOptions

  const columns = [
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string) => <Tag color={v === 'jd' ? 'blue' : 'orange'}>{v.toUpperCase()}</Tag>
    },
    { title: 'item_id', dataIndex: 'item_id', width: 160 },
    {
      title: '商品链接', width: 80,
      render: (_: unknown, record: UrlMapping) => {
        const url = record.item_url || buildUrl(record.platform, record.item_id)
        return url ? <a href={url} target="_blank" rel="noreferrer"><LinkOutlined /> 查看</a> : '-'
      }
    },
    {
      title: '品牌码', dataIndex: 'brand_code', width: 100,
      render: (v: string | null) => v ?? '-'
    },
    {
      title: '型号码', dataIndex: 'model_code', width: 160,
      render: (v: string | null) => v ? <Text code>{v}</Text> : '-'
    },
    {
      title: '品牌名', dataIndex: 'brand_name', width: 120,
      render: (v: string | null) => v ?? '-'
    },
    {
      title: '单价', dataIndex: 'price', width: 90,
      render: (v: number | null) => v != null ? `¥${v}` : '-'
    },
    {
      title: '操作', width: 120, fixed: 'right' as const,
      render: (_: unknown, record: UrlMapping) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space wrap>
          <Input.Search
            placeholder="搜索 item_id / 型号码 / 品牌码"
            allowClear
            style={{ width: 280 }}
            onSearch={v => { setKeyword(v); setPage(1) }}
          />
          <Select
            placeholder="平台筛选"
            allowClear
            style={{ width: 160 }}
            options={PLATFORM_OPTIONS}
            onChange={v => { setPlatform(v); setPage(1) }}
          />
          <Select
            placeholder="品类筛选"
            allowClear
            style={{ width: 140 }}
            options={categoryOptions}
            onChange={v => { setCategoryCode(v); setPage(1) }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>
          <Upload
            accept=".xlsx,.xls"
            showUploadList={false}
            beforeUpload={handleImport}
          >
            <Button icon={<UploadOutlined />} loading={importing}>导入 Excel</Button>
          </Upload>
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          scroll={{ x: 900 }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            onChange: setPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>

      <Modal
        title={editingId ? '编辑映射' : '新增映射'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {/* 品类辅助筛选，不提交 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 4, fontSize: 14 }}>品类（筛选型号用）</div>
            <Select
              allowClear
              placeholder="选择品类可缩小型号列表"
              style={{ width: '100%' }}
              options={categoryOptions}
              value={modalCategoryCode}
              onChange={v => setModalCategoryCode(v)}
            />
          </div>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={PLATFORM_OPTIONS} />
          </Form.Item>
          <Form.Item name="item_id" label="item_id" rules={[{ required: true }]}>
            <Input placeholder="如：100045223280" />
          </Form.Item>
          <Form.Item name="item_url" label="商品 URL">
            <Input placeholder="https://item.jd.com/..." />
          </Form.Item>
          <Form.Item name="model_id" label="型号" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder="搜索品牌/型号码"
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={filteredModelOptions.map(m => ({
                value: m.id,
                label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="price" label="单价（元）">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
