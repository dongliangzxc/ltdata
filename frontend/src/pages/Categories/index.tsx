// frontend/src/pages/Categories/index.tsx
import { useState } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input,
  InputNumber, Popconfirm, message, Typography, Select, Tag, Switch,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  getCategoryTree, createCategory, updateCategory, deleteCategory,
  listCategoryCustomFields, createCategoryCustomField, updateCategoryCustomField,
  deleteCategoryCustomField,
  type CategoryTreeNode, type CategoryCustomField,
} from '../../services/api'

const { Text } = Typography

function normalizeCategoryName(name: string): string {
  return (name || '').trim().normalize('NFKC').toLowerCase()
}

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

  const [fieldsCategory, setFieldsCategory] = useState<CategoryTreeNode | null>(null)
  const [customFields, setCustomFields] = useState<CategoryCustomField[]>([])
  const [fieldsLoading, setFieldsLoading] = useState(false)
  const [fieldModalOpen, setFieldModalOpen] = useState(false)
  const [editingField, setEditingField] = useState<CategoryCustomField | null>(null)
  const [fieldForm] = Form.useForm()

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

  const loadCustomFields = async (categoryCode: string) => {
    setFieldsLoading(true)
    try {
      const res = await listCategoryCustomFields(categoryCode)
      setCustomFields(res.data)
    } finally {
      setFieldsLoading(false)
    }
  }

  const openFields = (row: CategoryTreeNode) => {
    setFieldsCategory(row)
    setCustomFields([])
    void loadCustomFields(row.code)
  }

  const openAddField = () => {
    setEditingField(null)
    fieldForm.resetFields()
    fieldForm.setFieldsValue({
      field_type: 'enum',
      required: false,
      export: true,
      is_active: true,
      sort_order: 0,
    })
    setFieldModalOpen(true)
  }

  const openEditField = (field: CategoryCustomField) => {
    setEditingField(field)
    fieldForm.setFieldsValue({
      field_key: field.field_key,
      field_label: field.field_label,
      field_type: field.field_type,
      options: field.options ?? undefined,
      default_value: field.default_value ?? undefined,
      auto_keywords: field.auto_keywords ?? undefined,
      auto_value: field.auto_value ?? undefined,
      required: field.required,
      export: field.export,
      sort_order: field.sort_order,
      is_active: field.is_active,
    })
    setFieldModalOpen(true)
  }

  const handleSaveField = async () => {
    if (!fieldsCategory) return
    const values = await fieldForm.validateFields()
    const payload = {
      field_label: values.field_label,
      field_type: values.field_type,
      options: values.options || null,
      default_value: values.default_value || null,
      auto_keywords: values.auto_keywords || null,
      auto_value: values.auto_value || null,
      required: Boolean(values.required),
      export: Boolean(values.export),
      sort_order: values.sort_order ?? 0,
      is_active: Boolean(values.is_active),
    }
    if (editingField) {
      await updateCategoryCustomField(editingField.id, payload)
      message.success('字段已更新')
    } else {
      await createCategoryCustomField({
        ...payload,
        category_code: fieldsCategory.code,
        field_key: values.field_key,
      })
      message.success('字段已新增')
    }
    setFieldModalOpen(false)
    await loadCustomFields(fieldsCategory.code)
  }

  const handleDeleteField = async (field: CategoryCustomField) => {
    if (!fieldsCategory) return
    await deleteCategoryCustomField(field.id)
    message.success('字段已删除')
    await loadCustomFields(fieldsCategory.code)
  }

  const fieldColumns = [
    { title: '字段键', dataIndex: 'field_key', width: 120 },
    { title: '展示名', dataIndex: 'field_label', width: 100 },
    { title: '类型', dataIndex: 'field_type', width: 80 },
    { title: '可选值', dataIndex: 'options', width: 120, render: (v: string | null) => v || '-' },
    { title: '默认值', dataIndex: 'default_value', width: 80, render: (v: string | null) => v || '-' },
    { title: '自动关键词', dataIndex: 'auto_keywords', width: 140, render: (v: string | null) => v || '-' },
    { title: '自动值', dataIndex: 'auto_value', width: 80, render: (v: string | null) => v || '-' },
    { title: '导出', dataIndex: 'export', width: 60, render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>) },
    { title: '排序', dataIndex: 'sort_order', width: 60 },
    {
      title: '操作',
      width: 130,
      render: (_: unknown, field: CategoryCustomField) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditField(field)}>编辑</Button>
          <Popconfirm
            title="确认删除该字段？"
            description="已填写的人工值会保留，但不再展示。"
            onConfirm={() => handleDeleteField(field)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

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
      width: 230,
      render: (_: unknown, row: CategoryTreeNode) => (
        <Space size={4}>
          <Button size="small" icon={<SettingOutlined />} onClick={() => openFields(row)}>
            扩展字段
          </Button>
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
          <Form.Item
            name="name"
            label="品类名称"
            rules={[
              { required: true, whitespace: true, message: '请输入品类名称' },
              {
                validator: async (_, value: string) => {
                  const key = normalizeCategoryName(value)
                  if (!key) return
                  if (editing && key === normalizeCategoryName(editing.name)) return
                  if (flatAll.some(c => normalizeCategoryName(c.name) === key)) {
                    throw new Error('品类名称已存在')
                  }
                },
              },
            ]}
          >
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

      <Modal
        title={fieldsCategory ? `扩展字段 - ${fieldsCategory.name} (${fieldsCategory.code})` : '扩展字段'}
        open={!!fieldsCategory}
        onCancel={() => setFieldsCategory(null)}
        footer={null}
        width={980}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAddField}>新增字段</Button>
          <Table
            dataSource={customFields}
            rowKey="id"
            columns={fieldColumns}
            loading={fieldsLoading}
            pagination={false}
            size="small"
            scroll={{ x: 900 }}
          />
          <Text type="secondary">
            条目级字段会在清洗复核详情中展示并可人工修改；自动值按商品名称关键词实时计算，默认值在未命中时生效。
          </Text>
        </Space>
      </Modal>

      <Modal
        title={editingField ? '编辑扩展字段' : '新增扩展字段'}
        open={fieldModalOpen}
        onOk={handleSaveField}
        onCancel={() => setFieldModalOpen(false)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={fieldForm} layout="vertical">
          <Form.Item
            name="field_key"
            label="字段键"
            rules={[
              { required: true, message: '请输入字段键' },
              { pattern: /^[a-z][a-z0-9_]*$/, message: '小写字母开头，只能包含小写字母、数字、下划线' },
            ]}
          >
            <Input placeholder="如 is_smart" disabled={!!editingField} />
          </Form.Item>
          <Form.Item name="field_label" label="展示名" rules={[{ required: true, message: '请输入展示名' }]}>
            <Input placeholder="如 智能" />
          </Form.Item>
          <Form.Item name="field_type" label="字段类型" rules={[{ required: true, message: '请选择字段类型' }]}>
            <Select
              options={[
                { value: 'enum', label: '枚举（是/否、多选一）' },
                { value: 'text', label: '文本' },
                { value: 'bool', label: '布尔（是/否）' },
                { value: 'number', label: '数字' },
              ]}
            />
          </Form.Item>
          <Form.Item name="options" label="可选值（枚举用，逗号分隔）">
            <Input placeholder="如 是,否" />
          </Form.Item>
          <Form.Item name="default_value" label="默认值（未命中关键词时使用）">
            <Input placeholder="如 否" />
          </Form.Item>
          <Form.Item name="auto_keywords" label="自动关键词（商品名包含任一关键词时取自动值）">
            <Input.TextArea rows={2} placeholder="如 智能" />
          </Form.Item>
          <Form.Item name="auto_value" label="自动值">
            <Input placeholder="如 是" />
          </Form.Item>
          <Space size={24}>
            <Form.Item name="required" label="必填" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="export" label="参与导出" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="sort_order" label="排序值">
              <InputNumber min={0} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  )
}
