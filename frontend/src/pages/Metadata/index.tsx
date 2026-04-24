import { useState } from 'react'
import {
  Card, Table, Button, Input, Space, Popconfirm, Upload, Modal, Form,
  Select, Switch, InputNumber, message, Tag, Row, Col, Tooltip
} from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listMetadata, createMetadata, updateMetadata, deleteMetadata, importMetadata
} from '../../services/api'

type MetadataItem = {
  id: number
  category_code: string
  spec_name: string
  spec_type: string
  spec_values: string | null
  required: boolean
  decimal_places: number | null
  single_select: boolean
}

const SPEC_TYPE_OPTIONS = ['数值型', '文本型', '布尔型']

export default function MetadataPage() {
  const [search, setSearch] = useState<{ category_code?: string; spec_name?: string }>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<MetadataItem | null>(null)
  const [importing, setImporting] = useState(false)
  const [form] = Form.useForm()
  const specType = Form.useWatch('spec_type', form)

  const queryParams = { ...search, page, page_size: pageSize }
  const { data, loading, refresh } = useRequest(
    () => listMetadata(queryParams).then(r => r.data),
    { refreshDeps: [JSON.stringify(queryParams)] }
  )

  const openCreate = () => {
    setEditingItem(null)
    form.resetFields()
    form.setFieldsValue({ spec_type: '文本型', required: false, single_select: true })
    setModalOpen(true)
  }

  const openEdit = (item: MetadataItem) => {
    setEditingItem(item)
    form.setFieldsValue({
      category_code:  item.category_code,
      spec_name:      item.spec_name,
      spec_type:      item.spec_type,
      spec_values:    item.spec_values ?? '',
      required:       item.required,
      decimal_places: item.decimal_places,
      single_select:  item.single_select,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (editingItem) {
        await updateMetadata(editingItem.id, values)
        message.success('更新成功')
      } else {
        await createMetadata(values)
        message.success('新增成功')
      }
      setModalOpen(false)
      refresh()
    } catch {
      // error handled by interceptor
    }
  }

  const handleDelete = async (id: number) => {
    await deleteMetadata(id)
    message.success('已删除')
    refresh()
  }

  const handleImport = async (file: File) => {
    setImporting(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await importMetadata(formData)
      const { imported, upserted } = res.data
      message.success(`导入成功，处理 ${imported} 条，写入/更新 ${upserted} 条`)
      refresh()
    } catch {
      // error handled by interceptor
    } finally {
      setImporting(false)
    }
    return false
  }

  const columns = [
    { title: '品类码', dataIndex: 'category_code', width: 120 },
    { title: '规格名称', dataIndex: 'spec_name', width: 150 },
    {
      title: '规格类型', dataIndex: 'spec_type', width: 100,
      render: (v: string) => <Tag color={v === '数值型' ? 'blue' : v === '布尔型' ? 'purple' : 'default'}>{v}</Tag>
    },
    {
      title: '规格值（可选项）', dataIndex: 'spec_values',
      render: (v: string | null) => v
        ? <Tooltip title={v}><span style={{ color: '#666' }}>{v.length > 40 ? v.slice(0, 40) + '…' : v}</span></Tooltip>
        : '-'
    },
    {
      title: '必填', dataIndex: 'required', width: 70,
      render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Tag>否</Tag>
    },
    { title: '小数位', dataIndex: 'decimal_places', width: 80, render: (v: number | null) => v ?? '-' },
    {
      title: '单选', dataIndex: 'single_select', width: 70,
      render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag>
    },
    {
      title: '操作', width: 100, fixed: 'right' as const,
      render: (_: unknown, row: MetadataItem) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(row.id)} okText="删除" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <Card>
      <Row gutter={12} style={{ marginBottom: 16 }} align="middle">
        <Col>
          <Input
            placeholder="搜索品类码"
            allowClear
            style={{ width: 160 }}
            onChange={e => { setSearch(p => ({ ...p, category_code: e.target.value || undefined })); setPage(1) }}
          />
        </Col>
        <Col>
          <Input
            placeholder="搜索规格名称"
            allowClear
            style={{ width: 160 }}
            onChange={e => { setSearch(p => ({ ...p, spec_name: e.target.value || undefined })); setPage(1) }}
          />
        </Col>
        <Col flex="auto" />
        <Col>
          <Space>
            <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls">
              <Button icon={<UploadOutlined />} loading={importing}>Excel 导入</Button>
            </Upload>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>
          </Space>
        </Col>
      </Row>

      <Table
        dataSource={data?.items ?? []}
        columns={columns}
        rowKey="id"
        size="small"
        loading={loading}
        scroll={{ x: 900 }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
      />

      <Modal
        title={editingItem ? '编辑元数据规格' : '新增元数据规格'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="品类码" name="category_code" rules={[{ required: true, message: '请填写品类码' }]}>
                <Input placeholder="如 SB（Soundbar）" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="规格名称" name="spec_name" rules={[{ required: true, message: '请填写规格名称' }]}>
                <Input placeholder="如 SYSTEM TYPE" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="规格类型" name="spec_type" rules={[{ required: true }]}>
                <Select options={SPEC_TYPE_OPTIONS.map(v => ({ value: v, label: v }))} />
              </Form.Item>
            </Col>
            <Col span={12} style={{ display: specType === '数值型' ? undefined : 'none' }}>
              <Form.Item label="保留小数位" name="decimal_places">
                <InputNumber min={0} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            label="规格值（可选项）"
            name="spec_values"
            extra="多个可选值用英文逗号分隔，如 2.0,2.1,3.1"
          >
            <Input.TextArea rows={2} placeholder="2.0,2.1,3.1" />
          </Form.Item>
          <Row gutter={24}>
            <Col span={12}>
              <Form.Item label="必填" name="required" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="单选" name="single_select" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </Card>
  )
}
