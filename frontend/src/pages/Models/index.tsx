import { useMemo, useState } from 'react'
import {
  Card, Table, Button, Input, Space, Popconfirm, Modal, Form,
  InputNumber, message, Row, Col, Divider, Typography, Select, Tag
} from 'antd'
import {
  PlusOutlined, UploadOutlined, DownloadOutlined, EditOutlined, DeleteOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listModels, getModelDetail, createModel, updateModel, deleteModel,
  listModelAliases, addModelAlias, deleteModelAlias,
  listCategories, downloadModelTemplate,
} from '../../services/api'
import type { ModelItem as ApiModelItem, UserProfile } from '../../services/api'
import ImportMappingModal from '../../components/ImportMappingModal'
import CreateModelModal from '../../components/CreateModelModal'

const { Text } = Typography

function readStoredUser(): UserProfile | null {
  const raw = localStorage.getItem('auth_user')
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserProfile
  } catch {
    return null
  }
}

type ModelSpec = {
  id?: number
  spec_name: string
  spec_value?: string | null
}

type ModelAlias = {
  id: number
  alias_code: string
}

type ModelItem = ApiModelItem

export default function ModelsPage() {
  const [search, setSearch] = useState<Record<string, string | undefined>>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [modalOpen, setModalOpen] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<ModelItem | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [expandedSpecs, setExpandedSpecs] = useState<Record<number, ModelSpec[]>>({})
  const [form] = Form.useForm()

  const triggerDownload = (blob: Blob, filename: string) => {
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  }

  const handleDownloadTemplate = async () => {
    try {
      const res = await downloadModelTemplate()
      triggerDownload(res.data, '产品属性导入模板.xlsx')
    } catch {
      // handled by interceptor
    }
  }

  const [aliases, setAliases] = useState<ModelAlias[]>([])
  const [aliasInput, setAliasInput] = useState('')
  const [aliasLoading, setAliasLoading] = useState(false)

  const currentUser = readStoredUser()
  const { data: categoriesData } = useRequest(() => listCategories().then(r => r.data))
  const categoryOptions = (categoriesData ?? []).map((c: { code: string; name: string }) => ({
    value: c.code, label: `${c.name}（${c.code}）`
  }))
  const visibleCategoryOptions = useMemo(() => {
    if (!currentUser) return categoryOptions
    if (currentUser.is_admin === 1) return categoryOptions
    if (!currentUser.category_permissions?.length) return categoryOptions
    const allowed = new Set(currentUser.category_permissions)
    return categoryOptions.filter((option: { value: string; label: string }) => allowed.has(option.value))
  }, [categoryOptions, currentUser])

  const queryParams = { ...search, page, page_size: pageSize }
  const { data, loading, refresh } = useRequest(
    () => listModels(queryParams).then(r => r.data),
    { refreshDeps: [JSON.stringify(queryParams)] }
  )

  const openCreate = () => {
    setCreateModalOpen(true)
  }

  const openEdit = async (item: ModelItem) => {
    try {
      const res = await getModelDetail(item.id)
      const full: ModelItem = res.data
      setEditingItem(full)
      form.setFieldsValue({
        brand_code:    full.brand_code,
        model_code:    full.model_code,
        category_code: full.category_code,
        brand_name:    full.brand_name,
        model_name:    full.model_name,
        launch_year:   full.launch_year,
        launch_month:  full.launch_month,
        launch_week:   full.launch_week,
        launch_price:  full.launch_price,
        url:           full.url,
        status:        full.status ?? 'active',
        operator:      full.operator,
        specs:         full.specs,
      })
      const aliasRes = await listModelAliases(item.id)
      setAliases(aliasRes.data)
    } catch {
      // handled by interceptor
    }
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (editingItem) {
        await updateModel(editingItem.id, values)
        message.success('更新成功')
      } else {
        await createModel(values)
        message.success('新增成功')
      }
      setModalOpen(false)
      refresh()
    } catch {
      // handled by interceptor
    }
  }

  const handleDelete = async (id: number) => {
    await deleteModel(id)
    message.success('已删除')
    refresh()
  }

  const handleAddAlias = async () => {
    if (!editingItem || !aliasInput.trim()) return
    setAliasLoading(true)
    try {
      const res = await addModelAlias(editingItem.id, aliasInput.trim())
      setAliases(prev => [...prev, res.data])
      setAliasInput('')
    } catch {
      // handled by interceptor
    } finally {
      setAliasLoading(false)
    }
  }

  const handleDeleteAlias = async (aliasId: number) => {
    if (!editingItem) return
    try {
      await deleteModelAlias(editingItem.id, aliasId)
      setAliases(prev => prev.filter(a => a.id !== aliasId))
    } catch {
      // handled by interceptor
    }
  }

  const handleExpand = async (expanded: boolean, record: ModelItem) => {
    if (expanded && !expandedSpecs[record.id]) {
      try {
        const res = await getModelDetail(record.id)
        setExpandedSpecs(prev => ({ ...prev, [record.id]: res.data.specs ?? [] }))
      } catch {
        // handled by interceptor
      }
    }
  }

  const columns = [
    { title: '品类', dataIndex: 'category_name', width: 110, render: (v: string | null) => v || '-' },
    { title: '品牌', dataIndex: 'brand_name', width: 120, render: (v: string | null) => v || '-' },
    { title: '型号码', dataIndex: 'model_code', width: 130, render: (v: string | null) => v || <Tag color="warning">待补</Tag> },
    { title: '型号别名', dataIndex: 'model_name', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '修改时间', dataIndex: 'updated_at', width: 140,
      render: (v: string | null) => v || '-'
    },
    {
      title: '状态', dataIndex: 'status', width: 70,
      render: (v: string) => (
        <span style={{ color: v === 'active' ? '#52c41a' : '#ff4d4f' }}>
          {v === 'active' ? '启用' : '停用'}
        </span>
      )
    },
    {
      title: '操作人', dataIndex: 'operator', width: 90,
      render: (v: string | null) => v || '-'
    },
    {
      title: '操作', width: 90, fixed: 'right' as const,
      render: (_: unknown, row: ModelItem) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          <Popconfirm title="确认删除该型号及其所有规格？" onConfirm={() => handleDelete(row.id)} okText="删除" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  const specColumns = [
    { title: '规格名称', dataIndex: 'spec_name', width: 200 },
    { title: '规格值', dataIndex: 'spec_value', render: (v: string | null) => v || '-' },
  ]

  return (
    <Card>
      <Row gutter={12} style={{ marginBottom: 16 }} align="middle">
        <Col>
          <Select
            placeholder="品类筛选"
            allowClear
            style={{ width: 140 }}
            options={visibleCategoryOptions}
            onChange={v => { setSearch(p => ({ ...p, category_code: v || undefined })); setPage(1) }}
          />
        </Col>
        <Col>
          <Input
            placeholder="搜索品牌"
            allowClear
            style={{ width: 140 }}
            onChange={e => { setSearch(p => ({ ...p, brand_code: e.target.value || undefined })); setPage(1) }}
          />
        </Col>
        <Col>
          <Input
            placeholder="搜索型号/名称"
            allowClear
            style={{ width: 160 }}
            onChange={e => { setSearch(p => ({ ...p, keyword: e.target.value || undefined })); setPage(1) }}
          />
        </Col>
        <Col>
          <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 110 }}
            options={[
              { value: 'active', label: '启用' },
              { value: 'inactive', label: '停用' },
            ]}
            onChange={v => { setSearch(p => ({ ...p, status: v || undefined })); setPage(1) }}
          />
        </Col>
        <Col flex="auto" />
        <Col>
          <Space>
            <Button icon={<DownloadOutlined />} onClick={handleDownloadTemplate}>下载模板</Button>
            <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>Excel 导入</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增型号</Button>
          </Space>
        </Col>
      </Row>

      <Table
        dataSource={data?.items ?? []}
        columns={columns}
        rowKey="id"
        size="small"
        loading={loading}
        scroll={{ x: 'max-content' }}
        expandable={{
          onExpand: handleExpand,
          expandedRowRender: (record: ModelItem) => {
            const specs = expandedSpecs[record.id]
            if (!specs) return <Text type="secondary">加载中...</Text>
            if (specs.length === 0) return <Text type="secondary">暂无规格参数</Text>
            return (
              <Table
                dataSource={specs}
                columns={specColumns}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                style={{ margin: '8px 0' }}
              />
            )
          },
        }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
      />

      <ImportMappingModal
        open={importOpen}
        module="model"
        standardFields={[
          { value: 'brand_code', label: '品牌码', required: true },
          { value: 'model_code', label: '型号码', required: true },
          { value: 'category_code', label: '品类码' },
          { value: 'brand_name', label: '品牌名' },
          { value: 'model_name', label: '型号名' },
          { value: 'launch_year', label: '上市年' },
          { value: 'launch_month', label: '上市月' },
          { value: 'launch_week', label: '上市周' },
          { value: 'launch_price', label: '上市价' },
          { value: 'url', label: '链接' },
        ]}
        headersUrl="/models/headers"
        confirmUrl="/models/confirm"
        onSuccess={() => { refresh() }}
        onClose={() => setImportOpen(false)}
      />

      <CreateModelModal
        open={createModalOpen}
        categoryOptions={visibleCategoryOptions}
        onCancel={() => setCreateModalOpen(false)}
        onCreated={() => {
          setCreateModalOpen(false)
          refresh()
        }}
      />

      <Modal
        title="编辑型号"
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={620}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>基本信息</Divider>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item label="品类" name="category_code">
                <Select placeholder="请选择品类" allowClear options={visibleCategoryOptions} showSearch
                  filterOption={(input, opt) => (opt?.label as string ?? '').toLowerCase().includes(input.toLowerCase())} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="品牌码" name="brand_code" rules={[{ required: true, message: '请填写品牌码' }]}>
                <Input placeholder="如 SONY" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="型号码" name="model_code" rules={[{ required: true, message: '请填写型号码' }]}>
                <Input placeholder="如 HT-A7000" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="品牌名称" name="brand_name">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="型号名称" name="model_name">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item label="上市年" name="launch_year">
                <InputNumber style={{ width: '100%' }} min={2000} max={2099} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="上市月" name="launch_month">
                <InputNumber style={{ width: '100%' }} min={1} max={12} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="上市周" name="launch_week">
                <InputNumber style={{ width: '100%' }} min={1} max={53} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="上市价格" name="launch_price">
                <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="网址" name="url">
            <Input placeholder="https://..." />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item label="状态" name="status" initialValue="active">
                <Select options={[
                  { value: 'active', label: '启用' },
                  { value: 'inactive', label: '停用' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item label="操作人" name="operator">
                <Input placeholder="如 alice" />
              </Form.Item>
            </Col>
          </Row>

          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>规格参数</Divider>
          <Form.List name="specs">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name }) => (
                  <Row key={key} gutter={8} align="middle" style={{ marginBottom: 6 }}>
                    <Col span={10}>
                      <Form.Item name={[name, 'spec_name']} noStyle rules={[{ required: true, message: '请填写规格名称' }]}>
                        <Input placeholder="规格名称*" />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name={[name, 'spec_value']} noStyle>
                        <Input placeholder="规格值（多值逗号分隔）" />
                      </Form.Item>
                    </Col>
                    <Col span={2} style={{ textAlign: 'center' }}>
                      <MinusCircleOutlined onClick={() => remove(name)} style={{ color: '#ff4d4f', cursor: 'pointer' }} />
                    </Col>
                  </Row>
                ))}
                <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} block style={{ marginTop: 4 }}>
                  添加规格
                </Button>
              </>
            )}
          </Form.List>

          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>别名</Divider>
          {editingItem ? (
            <>
              <div style={{ marginBottom: 8 }}>
                {aliases.map(a => (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ flex: 1, fontSize: 13 }}>{a.alias_code}</span>
                    <Popconfirm
                      title="确认删除该别名？"
                      onConfirm={() => handleDeleteAlias(a.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button type="link" size="small" danger icon={<MinusCircleOutlined />} />
                    </Popconfirm>
                  </div>
                ))}
                {aliases.length === 0 && (
                  <div style={{ fontSize: 12, color: '#aaa' }}>暂无别名</div>
                )}
              </div>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="输入别名后回车或点击添加"
                  value={aliasInput}
                  onChange={e => setAliasInput(e.target.value)}
                  onPressEnter={handleAddAlias}
                  style={{ flex: 1 }}
                />
                <Button
                  type="primary"
                  loading={aliasLoading}
                  onClick={handleAddAlias}
                  icon={<PlusOutlined />}
                >
                  添加
                </Button>
              </Space.Compact>
            </>
          ) : (
            <div style={{ fontSize: 12, color: '#aaa' }}>新增型号保存后再添加别名</div>
          )}
        </Form>
      </Modal>
    </Card>
  )
}
