import { useState, useRef } from 'react'
import {
  Card, Table, Button, Input, Space, Popconfirm, Upload, Modal, Form,
  InputNumber, message, Row, Col, Divider, Typography, Collapse
} from 'antd'
import {
  PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined,
  MinusCircleOutlined, CheckCircleOutlined, WarningOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listModels, getModelDetail, createModel, updateModel, deleteModel,
  importModels, previewModels,
  listModelAliases, addModelAlias, deleteModelAlias,
} from '../../services/api'

const { Text } = Typography

type ModelSpec = {
  id?: number
  spec_name: string
  spec_value?: string | null
}

type ModelAlias = {
  id: number
  alias_code: string
}

type ModelItem = {
  id: number
  brand_code: string
  model_code: string
  category_name?: string | null
  brand_name?: string | null
  model_name?: string | null
  launch_year?: number | null
  launch_month?: number | null
  launch_week?: number | null
  launch_price?: number | null
  url?: string | null
  specs: ModelSpec[]
  aliases: ModelAlias[]
}

type PreviewResult = {
  total_rows: number
  valid_rows: number
  spec_rows: number
  preview: Record<string, unknown>[]
  errors: { row: number; message: string }[]
  warnings: { row: number; message: string }[]
}

export default function ModelsPage() {
  const [search, setSearch] = useState<Record<string, string | undefined>>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<ModelItem | null>(null)
  const [importing, setImporting] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null)
  const pendingFileRef = useRef<File | null>(null)
  const [expandedSpecs, setExpandedSpecs] = useState<Record<number, ModelSpec[]>>({})
  const [form] = Form.useForm()

  const [aliases, setAliases] = useState<ModelAlias[]>([])
  const [aliasInput, setAliasInput] = useState('')
  const [aliasLoading, setAliasLoading] = useState(false)

  const queryParams = { ...search, page, page_size: pageSize }
  const { data, loading, refresh } = useRequest(
    () => listModels(queryParams).then(r => r.data),
    { refreshDeps: [JSON.stringify(queryParams)] }
  )

  const openCreate = () => {
    setEditingItem(null)
    form.resetFields()
    form.setFieldsValue({ specs: [] })
    setAliases([])
    setAliasInput('')
    setModalOpen(true)
  }

  const openEdit = async (item: ModelItem) => {
    try {
      const res = await getModelDetail(item.id)
      const full: ModelItem = res.data
      setEditingItem(full)
      form.setFieldsValue({
        brand_code:    full.brand_code,
        model_code:    full.model_code,
        category_name: full.category_name,
        brand_name:    full.brand_name,
        model_name:    full.model_name,
        launch_year:   full.launch_year,
        launch_month:  full.launch_month,
        launch_week:   full.launch_week,
        launch_price:  full.launch_price,
        url:           full.url,
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

  const handleImport = async (file: File) => {
    setPreviewing(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await previewModels(formData)
      pendingFileRef.current = file
      setPreviewResult(res.data)
      setPreviewOpen(true)
    } catch {
      // handled by interceptor
    } finally {
      setPreviewing(false)
    }
    return false
  }

  const handleConfirmImport = async () => {
    if (!pendingFileRef.current) return
    setImporting(true)
    const formData = new FormData()
    formData.append('file', pendingFileRef.current)
    try {
      const res = await importModels(formData)
      const { imported_models, imported_specs } = res.data
      message.success(`导入成功，型号 ${imported_models} 条，规格 ${imported_specs} 条`)
      setPreviewOpen(false)
      pendingFileRef.current = null
      setPreviewResult(null)
      refresh()
    } catch {
      // handled by interceptor
    } finally {
      setImporting(false)
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
    { title: '型号码', dataIndex: 'model_code', width: 130 },
    { title: '型号名', dataIndex: 'model_name', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '上市年月', width: 100,
      render: (_: unknown, row: ModelItem) => {
        const y = row.launch_year, m = row.launch_month
        return y ? `${y}${m ? `-${String(m).padStart(2, '0')}` : ''}` : '-'
      }
    },
    {
      title: '上市价', dataIndex: 'launch_price', width: 100,
      render: (v: number | null) => v != null ? `¥${Number(v).toLocaleString()}` : '-'
    },
    {
      title: '网址', dataIndex: 'url', width: 70,
      render: (v: string | null) => v ? <a href={v} target="_blank" rel="noreferrer">查看</a> : '-'
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
        <Col flex="auto" />
        <Col>
          <Space>
            <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls">
              <Button icon={<UploadOutlined />} loading={previewing || importing}>Excel 导入</Button>
            </Upload>
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
        scroll={{ x: 800 }}
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

      {/* Excel 预览确认 Modal */}
      <Modal
        title="Excel 导入预览"
        open={previewOpen}
        onCancel={() => { setPreviewOpen(false); pendingFileRef.current = null; setPreviewResult(null) }}
        onOk={handleConfirmImport}
        okText="确认导入"
        cancelText="取消"
        okButtonProps={{ loading: importing }}
        width={700}
      >
        {previewResult && (
          <>
            <Row gutter={16} style={{ marginBottom: 12 }}>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 22, fontWeight: 600 }}>{previewResult.total_rows}</div>
                  <div style={{ color: '#888', fontSize: 12 }}>读取行数</div>
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 22, fontWeight: 600, color: '#3f8600' }}>{previewResult.valid_rows}</div>
                  <div style={{ color: '#888', fontSize: 12 }}>有效型号</div>
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 22, fontWeight: 600, color: '#1677ff' }}>{previewResult.spec_rows}</div>
                  <div style={{ color: '#888', fontSize: 12 }}>规格行数</div>
                </Card>
              </Col>
            </Row>

            {previewResult.errors.length > 0 && (
              <Collapse
                size="small"
                style={{ marginBottom: 8 }}
                items={[{
                  key: 'errors',
                  label: <><WarningOutlined style={{ color: '#cf1322' }} /> 错误 {previewResult.errors.length} 条（这些行将被跳过）</>,
                  children: previewResult.errors.map(e => (
                    <div key={e.row} style={{ fontSize: 12, color: '#cf1322' }}>第 {e.row} 行：{e.message}</div>
                  )),
                }]}
              />
            )}

            {previewResult.warnings.length > 0 && (
              <Collapse
                size="small"
                style={{ marginBottom: 8 }}
                items={[{
                  key: 'warnings',
                  label: <><CheckCircleOutlined style={{ color: '#d46b08' }} /> 警告 {previewResult.warnings.length} 条</>,
                  children: previewResult.warnings.map((w, i) => (
                    <div key={i} style={{ fontSize: 12, color: '#d46b08' }}>第 {w.row} 行：{w.message}</div>
                  )),
                }]}
              />
            )}

            {previewResult.valid_rows > 0 && (
              <>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>
                  预览（前 {previewResult.preview.length} 条）：
                </div>
                <Table
                  dataSource={previewResult.preview}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  scroll={{ x: 500 }}
                  columns={[
                    { title: '品牌码', dataIndex: 'brand_code', width: 90 },
                    { title: '型号码', dataIndex: 'model_code', width: 110 },
                    { title: '品牌名', dataIndex: 'brand_name', width: 90 },
                    { title: '型号名', dataIndex: 'model_name', ellipsis: true },
                    { title: '上市年', dataIndex: 'launch_year', width: 75 },
                    { title: '上市价', dataIndex: 'launch_price', width: 80,
                      render: (v: number | null) => v != null ? `¥${Number(v).toLocaleString()}` : '-' },
                  ]}
                />
              </>
            )}
          </>
        )}
      </Modal>

      <Modal
        title={editingItem ? '编辑型号' : '新增型号'}
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
              <Form.Item label="品类名称" name="category_name">
                <Input placeholder="如 SOUNDBAR" />
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
