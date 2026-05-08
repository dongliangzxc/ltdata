// frontend/src/pages/Categories/index.tsx
import { useState } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input,
  Popconfirm, message, Typography,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listCategories, createCategory, updateCategory, deleteCategory } from '../../services/api'

const { Text } = Typography

type Category = {
  id: number
  code: string
  name: string
  created_at: string
}

export default function CategoriesPage() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Category | null>(null)
  const [form] = Form.useForm()

  const { data, loading, refresh } = useRequest(
    () => listCategories().then(r => r.data as Category[]),
  )

  const openAdd = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (row: Category) => {
    setEditing(row)
    form.setFieldsValue({ name: row.name })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    if (editing) {
      await updateCategory(editing.id, { name: values.name })
      message.success('更新成功')
    } else {
      await createCategory({ code: values.code, name: values.name })
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const handleDelete = async (row: Category) => {
    try {
      await deleteCategory(row.id)
      message.success('已删除')
      refresh()
    } catch {
      // 错误由 axios interceptor 全局展示
    }
  }

  const columns = [
    { title: '品类码', dataIndex: 'code', width: 140,
      render: (v: string) => <Text code>{v}</Text> },
    { title: '品类名称', dataIndex: 'name' },
    { title: '创建时间', dataIndex: 'created_at', width: 180,
      render: (v: string) => v ? v.slice(0, 19).replace('T', ' ') : '-' },
    {
      title: '操作', width: 140,
      render: (_: unknown, row: Category) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            改名
          </Button>
          <Popconfirm
            title="确认删除该品类？"
            description="若品类下有型号或规格，将无法删除。"
            onConfirm={() => handleDelete(row)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            新增品类
          </Button>
        }
      >
        <Table
          dataSource={data ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={{ pageSize: 50, showTotal: (t: number) => `共 ${t} 个品类` }}
        />
      </Card>

      <Modal
        title={editing ? '编辑品类名称' : '新增品类'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item
              label="品类码（唯一标识，创建后不可修改）"
              name="code"
              rules={[
                { required: true, message: '请输入品类码' },
                { pattern: /^[a-z0-9_-]+$/, message: '只能包含小写字母、数字、下划线、连字符' },
              ]}
            >
              <Input placeholder="如 soundbar、tv、headphone" />
            </Form.Item>
          )}
          <Form.Item
            label="品类名称（显示用）"
            name="name"
            rules={[{ required: true, message: '请输入品类名称' }]}
          >
            <Input placeholder="如 回音壁、电视、耳机" />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
