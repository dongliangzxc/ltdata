// frontend/src/pages/Brands/index.tsx
import { useMemo, useState } from 'react'
import {
  Card, Table, Button, Space, Popconfirm, message, Tag, Form, Modal, Input, Select,
} from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listBrands, listBrandAliasesByCode, createBrandAliasForCode, deleteBrandAliasById,
  updateBrand, updateBrandAliasForCode,
  type BrandItem, type BrandAliasItem,
} from '../../services/api'
import CreateBrandModal from '../../components/CreateBrandModal'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

function AliasPanel({ brandCode, onAliasChange }: { brandCode: string; onAliasChange: () => void }) {
  const [addOpen, setAddOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editingAlias, setEditingAlias] = useState<BrandAliasItem | null>(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const { data: aliases, loading, refresh } = useRequest(
    () => listBrandAliasesByCode(brandCode).then(r => r.data),
  )

  const handleAdd = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const aliasName = values.alias_name.trim()
      await createBrandAliasForCode(brandCode, { alias_name: aliasName })
      message.success('别名添加成功')
      form.resetFields()
      setAddOpen(false)
      refresh()
      onAliasChange()
    } catch {
      // errors shown by axios interceptor
    } finally {
      setSaving(false)
    }
  }

  const openEdit = (alias: BrandAliasItem) => {
    setEditingAlias(alias)
    editForm.setFieldsValue({ alias_name: alias.alias_name })
    setEditOpen(true)
  }

  const closeEdit = () => {
    setEditOpen(false)
    setEditingAlias(null)
    editForm.resetFields()
  }

  const handleEdit = async () => {
    if (!editingAlias) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      const aliasName = values.alias_name.trim()
      await updateBrandAliasForCode(brandCode, editingAlias.id, { alias_name: aliasName })
      message.success('别名已更新')
      closeEdit()
      refresh()
      onAliasChange()
    } catch {
      // errors shown by axios interceptor
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (alias: BrandAliasItem) => {
    try {
      await deleteBrandAliasById(brandCode, alias.id)
      message.success('已删除')
      refresh()
      onAliasChange()
    } catch {
      // errors shown by axios interceptor
    }
  }

  const columns = [
    { title: '写法别名', dataIndex: 'alias_name' },
    {
      title: '操作',
      width: 132,
      render: (_: unknown, row: BrandAliasItem) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该别名？"
            onConfirm={() => handleDelete(row)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '8px 0 8px 48px' }}>
      <Space style={{ marginBottom: 8 }}>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
          添加别名
        </Button>
      </Space>
      <Table
        dataSource={aliases ?? []}
        rowKey="id"
        columns={columns}
        loading={loading}
        pagination={false}
        size="small"
      />
      <Modal
        title={`为 ${brandCode} 添加写法别名`}
        open={addOpen}
        onOk={handleAdd}
        confirmLoading={saving}
        onCancel={() => { setAddOpen(false); form.resetFields() }}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="alias_name" label="别名写法" rules={[{ required: true, message: '请输入别名' }]}>
            <Input placeholder="e.g. Sony / SONY INC / 索尼" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="修改品牌别名"
        open={editOpen}
        onOk={handleEdit}
        confirmLoading={saving}
        onCancel={closeEdit}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="品牌码">
            <Input value={brandCode} disabled />
          </Form.Item>
          <Form.Item name="alias_name" label="别名写法" rules={[{ required: true, message: '请输入别名' }]}>
            <Input placeholder="e.g. Sony / SONY INC / 索尼" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default function BrandsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [selectedCategoryCode, setSelectedCategoryCode] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editingBrand, setEditingBrand] = useState<BrandItem | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editForm] = Form.useForm<{ brand_name: string; alias_name: string }>()

  const { data: brands, loading, refresh, mutate } = useRequest(
    () => listBrands().then(r => r.data),
  )
  const { options: categoryOptions, loading: categoryLoading } = useCategoryOptions()
  const categoryLabelMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of categoryOptions) m.set(c.value, c.label)
    return m
  }, [categoryOptions])

  const renderOptionalText = (v: string | null | undefined) =>
    v && v.trim() ? v : <span style={{ color: '#ccc' }}>—</span>

  const filteredBrands = useMemo(() => {
    const brandList = brands || []
    const keyword = searchText.trim().toLowerCase()
    if (!keyword && !selectedCategoryCode) return brandList
    return brandList.filter((brand) => {
      const matchesKeyword = !keyword || [brand.brand_code, brand.original_brand_name, brand.brand_name]
        .some(value => (value || '').toLowerCase().includes(keyword))
      const matchesCategory = !selectedCategoryCode || (brand.category_codes || []).includes(selectedCategoryCode)
      return matchesKeyword && matchesCategory
    })
  }, [brands, searchText, selectedCategoryCode])

  const openEdit = (brand: BrandItem) => {
    setEditingBrand(brand)
    editForm.setFieldsValue({
      brand_name: brand.brand_name || '',
      alias_name: brand.primary_alias_name || '',
    })
    setEditOpen(true)
  }

  const closeEdit = () => {
    setEditOpen(false)
    setEditingBrand(null)
    editForm.resetFields()
  }

  const handleEditSave = async () => {
    if (!editingBrand) return
    const values = await editForm.validateFields()
    const trimmedName = values.brand_name?.trim() || ''
    const trimmedAliasName = values.alias_name?.trim() || ''
    setEditSaving(true)
    try {
      const { data: updatedBrand } = await updateBrand(editingBrand.brand_code, {
        brand_name: trimmedName || null,
        alias_name: trimmedAliasName || null,
      })
      mutate((currentBrands = []) => currentBrands.map(brand => (
        brand.brand_code === updatedBrand.brand_code ? updatedBrand : brand
      )))
      refresh()
      message.success('品牌信息已更新')
      closeEdit()
    } finally {
      setEditSaving(false)
    }
  }

  const columns = [
    {
      title: '品牌码',
      dataIndex: 'brand_code',
      width: 140,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '上传时品牌名称',
      dataIndex: 'original_brand_name',
      width: 160,
      render: (v: string | null) => renderOptionalText(v),
    },
    {
      title: '修改后名称',
      dataIndex: 'brand_name',
      width: 160,
      render: (v: string | null) => renderOptionalText(v),
    },
    {
      title: '品类',
      dataIndex: 'category_codes',
      render: (codes: string[] | undefined) => {
        if (!codes || codes.length === 0) return <span style={{ color: '#ccc' }}>—</span>
        return (
          <Space size={[4, 4]} wrap>
            {codes.map(code => (
              <Tag key={code}>{categoryLabelMap.get(code) ?? code}</Tag>
            ))}
          </Space>
        )
      },
    },
    { title: '型号数', dataIndex: 'model_count', width: 90 },
    { title: '写法别名数', dataIndex: 'alias_count', width: 110 },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: BrandItem) => (
        <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ]

  return (
    <Card
      title="品牌管理"
      extra={(
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建品牌
        </Button>
      )}
    >
      <Space size={12} wrap style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="搜索品牌码 / 上传时品牌名称 / 修改后名称"
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{ width: 420 }}
        />
        <Select
          allowClear
          loading={categoryLoading}
          placeholder="筛选品类"
          value={selectedCategoryCode}
          onChange={value => setSelectedCategoryCode(value)}
          options={categoryOptions}
          showSearch
          optionFilterProp="label"
          style={{ width: 180 }}
        />
      </Space>
      <Table
        dataSource={filteredBrands}
        rowKey="brand_code"
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
        expandable={{
          expandedRowRender: (record: BrandItem) => (
            <AliasPanel brandCode={record.brand_code} onAliasChange={refresh} />
          ),
        }}
      />
      <CreateBrandModal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false)
          refresh()
        }}
      />
      <Modal
        title="修改品牌名称"
        open={editOpen}
        onOk={handleEditSave}
        confirmLoading={editSaving}
        onCancel={closeEdit}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="品牌码">
            <Input value={editingBrand?.brand_code || ''} disabled />
          </Form.Item>
          <Form.Item name="brand_name" label="修改后名称">
            <Input placeholder="留空则恢复默认显示" />
          </Form.Item>
          <Form.Item name="alias_name" label="品牌别名">
            <Input placeholder="品牌创建时录入的别名" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
