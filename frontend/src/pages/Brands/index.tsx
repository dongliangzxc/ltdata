// frontend/src/pages/Brands/index.tsx
import { useState } from 'react'
import {
  Card, Table, Button, Space, Popconfirm, message, Tag, Form, Modal, Input,
} from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listBrands, listBrandAliasesByCode, createBrandAliasForCode, deleteBrandAliasById,
  type BrandItem, type BrandAliasItem,
} from '../../services/api'
import CreateBrandModal from '../../components/CreateBrandModal'

function AliasPanel({ brandCode, onAliasChange }: { brandCode: string; onAliasChange: () => void }) {
  const [addOpen, setAddOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const { data: aliases, loading, refresh } = useRequest(
    () => listBrandAliasesByCode(brandCode).then(r => r.data),
  )

  const handleAdd = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await createBrandAliasForCode(brandCode, { alias_name: values.alias_name })
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
      width: 80,
      render: (_: unknown, row: BrandAliasItem) => (
        <Popconfirm
          title="确认删除该别名？"
          onConfirm={() => handleDelete(row)}
          okText="删除"
          cancelText="取消"
        >
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
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
    </div>
  )
}

export default function BrandsPage() {
  const [createOpen, setCreateOpen] = useState(false)

  const { data: brands, loading, refresh } = useRequest(
    () => listBrands().then(r => r.data),
  )

  const columns = [
    {
      title: '品牌码',
      dataIndex: 'brand_code',
      width: 140,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '品牌名称',
      dataIndex: 'brand_name',
      render: (v: string | null) => v ?? <span style={{ color: '#ccc' }}>—</span>,
    },
    { title: '型号数', dataIndex: 'model_count', width: 90 },
    { title: '写法别名数', dataIndex: 'alias_count', width: 110 },
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
      <Table
        dataSource={brands ?? []}
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
    </Card>
  )
}
