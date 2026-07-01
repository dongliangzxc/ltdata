import { useState } from 'react'
import {
  Card, Table, Button, Input, Select, Space, Typography,
  Modal, Form, InputNumber, message, Popconfirm, Tag,
} from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUrlMappings, createUrlMapping, updateUrlMapping,
  deleteUrlMapping, listModels,
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
import ImportMappingModal from '../../components/ImportMappingModal'

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
  category_code: string | null
  category_name: string | null
  item_name: string | null
  source: string | null
  data_year: number | null
  data_month: number | null
  operator: string | null
  updated_at: string | null
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

export default function UrlMappingsPage() {
  const [keyword, setKeyword] = useState('')
  const [platform, setPlatform] = useState<string | undefined>()
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [modalCategoryCode, setModalCategoryCode] = useState<string | undefined>()

  const [filterYear, setFilterYear] = useState<number | undefined>()
  const [filterMonth, setFilterMonth] = useState<number | undefined>()

  const { options: categoryOptions } = useCategoryOptions()

  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 500 }).then(r => r.data)
  )
  const modelOptions: ModelOption[] = (modelsData?.items ?? []).map(m => ({
    id: m.id,
    brand_code: m.brand_code,
    model_code: m.model_code,
    brand_name: m.brand_name ?? null,
    model_name: m.model_name ?? null,
    category_code: m.category_code ?? null,
  }))

  const { data, loading, refresh } = useRequest(
    () => listUrlMappings({
      keyword: keyword || undefined,
      platform: platform || undefined,
      category_code: categoryCode || undefined,
      year: filterYear,
      month: filterMonth,
      page,
      page_size: 20,
    }).then(r => r.data),
    { refreshDeps: [keyword, platform, categoryCode, filterYear, filterMonth, page] }
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

  const filteredModelOptions = modalCategoryCode
    ? modelOptions.filter(m => m.category_code === modalCategoryCode)
    : modelOptions

  const columns = [
    {
      title: '品类', width: 120,
      render: (_: unknown, record: UrlMapping) => record.category_name || record.category_code || '-'
    },
    {
      title: '品牌', width: 120,
      render: (_: unknown, record: UrlMapping) => record.brand_name || record.brand_code || '-'
    },
    {
      title: '型号', dataIndex: 'model_code', width: 140,
      render: (v: string | null) => v ? <Text code>{v}</Text> : '-'
    },
    {
      title: '型号别名', dataIndex: 'model_name', width: 160,
      render: (v: string | null) => v || '-'
    },
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true, width: 240,
      render: (v: string | null) => v || '-'
    },
    {
      title: '判断类型',
      dataIndex: 'source',
      width: 110,
      render: (v: string | null) => {
        const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
          model_db_import: { label: '型号库导入', color: 'purple' },
          url_import:      { label: 'URL导入',   color: 'blue'   },
          match_confirm:   { label: '匹配确认',   color: 'green'  },
          manual:          { label: '手动创建',   color: 'orange' },
        }
        const cfg = v ? SOURCE_LABELS[v] : null
        return cfg
          ? <Tag color={cfg.color}>{cfg.label}</Tag>
          : <span style={{ color: '#ccc' }}>—</span>
      },
    },
    {
      title: '修改时间', dataIndex: 'updated_at', width: 150,
      render: (v: string | null) => v || '-'
    },
    {
      title: '操作人', dataIndex: 'operator', width: 90,
      render: (v: string | null) => v || '-'
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
          <InputNumber
            placeholder="年份"
            value={filterYear}
            onChange={v => { setFilterYear(v ?? undefined); setPage(1) }}
            min={2020}
            max={2099}
            style={{ width: 100 }}
          />
          <Select
            placeholder="月份"
            value={filterMonth}
            onChange={v => { setFilterMonth(v); setPage(1) }}
            allowClear
            style={{ width: 90 }}
            options={Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }))}
          />
          <Select
            placeholder="品类筛选"
            allowClear
            style={{ width: 140 }}
            options={categoryOptions}
            onChange={v => { setCategoryCode(v); setPage(1) }}
          />
          <Select
            placeholder="平台筛选"
            allowClear
            style={{ width: 160 }}
            options={PLATFORM_OPTIONS}
            onChange={v => { setPlatform(v); setPage(1) }}
          />
          <Input.Search
            placeholder="搜索 item_id / 型号 / 品牌"
            allowClear
            style={{ width: 280 }}
            onSearch={v => { setKeyword(v); setPage(1) }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>
          <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入 Excel</Button>
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          scroll={{ x: 1250 }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            onChange: setPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>

      <ImportMappingModal
        open={importOpen}
        module="url"
        standardFields={[
          { value: 'platform', label: '平台', required: true },
          { value: 'item_url', label: '商品链接', required: true },
          { value: 'brand_code', label: '品牌码', required: true },
          { value: 'model_code', label: '型号码', required: true },
          { value: 'price', label: '价格' },
        ]}
        headersUrl="/url-mappings/headers"
        confirmUrl="/url-mappings/confirm"
        onSuccess={() => { refresh() }}
        onClose={() => setImportOpen(false)}
      />

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
