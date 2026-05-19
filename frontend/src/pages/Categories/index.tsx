// frontend/src/pages/Categories/index.tsx
import { useState } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input,
  InputNumber, Popconfirm, message, Typography, Select,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  getCategoryTree, createCategory, updateCategory, deleteCategory,
  type CategoryTreeNode,
} from '../../services/api'

const { Text } = Typography

function flattenTree(nodes: CategoryTreeNode[]): CategoryTreeNode[] {
  return nodes.flatMap(n => [n, ...flattenTree(n.children)])
}

function getDescendantCodes(treeNodes: CategoryTreeNode[], targetCode: string): Set<string> {
  const descendants = new Set<string>()
  function walk(nodes: CategoryTreeNode[]) {
    for (const n of nodes) {
      if (n.code === targetCode) {
        // collect all children recursively
        function collectAll(children: CategoryTreeNode[]) {
          for (const c of children) {
            descendants.add(c.code)
            collectAll(c.children)
          }
        }
        collectAll(n.children)
      } else {
        walk(n.children)
      }
    }
  }
  walk(treeNodes)
  return descendants
}

export default function CategoriesPage() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<CategoryTreeNode | null>(null)
  const [form] = Form.useForm()

  const { data: treeData, loading, refresh } = useRequest(
    () => getCategoryTree().then(r => r.data),
  )

  const flatAll = flattenTree(treeData ?? [])
  const descendantCodes = editing ? getDescendantCodes(treeData ?? [], editing.code) : new Set<string>()

  const openAdd = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (row: CategoryTreeNode) => {
    setEditing(row)
    form.setFieldsValue({
      name: row.name,
      parent_code: row.parent_code ?? undefined,
      sort_order: row.sort_order,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    if (editing) {
      await updateCategory(editing.id, {
        name: values.name,
        parent_code: values.parent_code ?? null,
        sort_order: values.sort_order ?? 0,
      })
      message.success('更新成功')
    } else {
      await createCategory({
        code: values.code,
        name: values.name,
        parent_code: values.parent_code ?? undefined,
        sort_order: values.sort_order ?? 0,
      })
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const handleDelete = async (row: CategoryTreeNode) => {
    try {
      await deleteCategory(row.id)
      message.success('已删除')
      refresh()
    } catch {
      // 错误由 axios interceptor 全局展示
    }
  }

  const columns = [
    {
      title: '品类名称',
      dataIndex: 'name',
      render: (v: string, row: CategoryTreeNode) => (
        <Space>
          <Text strong={!row.parent_code}>{v}</Text>
          <Text code type="secondary">{row.code}</Text>
        </Space>
      ),
    },
    { title: '排序值', dataIndex: 'sort_order', width: 80 },
    {
      title: '操作',
      width: 140,
      render: (_: unknown, row: CategoryTreeNode) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该品类？"
            description="若品类下有型号或规格，将无法删除。"
            onConfirm={() => handleDelete(row)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="品类管理"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新增品类</Button>}
    >
      <Table
        dataSource={treeData ?? []}
        rowKey="code"
        columns={columns}
        loading={loading}
        pagination={false}
        size="small"
        expandable={{ defaultExpandAllRows: true }}
      />

      <Modal
        title={editing ? '编辑品类' : '新增品类'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item
              name="code"
              label="品类码"
              rules={[
                { required: true, message: '请输入品类码' },
                { pattern: /^[a-z0-9_-]+$/, message: '只能包含小写字母、数字、下划线、连字符' }
              ]}
            >
              <Input placeholder="e.g. headphones" />
            </Form.Item>
          )}
          <Form.Item name="name" label="品类名称" rules={[{ required: true, message: '请输入品类名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="parent_code" label="父品类（留空表示顶级）">
            <Select
              allowClear
              placeholder="选择父品类"
              options={flatAll
                .filter(c => !editing || (c.code !== editing.code && !descendantCodes.has(c.code)))
                .map(c => ({ value: c.code, label: `${c.name} (${c.code})` }))}
            />
          </Form.Item>
          <Form.Item name="sort_order" label="排序值" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
