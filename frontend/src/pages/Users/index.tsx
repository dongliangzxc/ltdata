import { useMemo, useState } from 'react'
import {
  Button, Card, Checkbox, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  createUser, listUsers, resetUserPassword, updateUser,
  type CreateUserPayload, type ManagedUser, type PermissionKey, type UpdateUserPayload,
} from '../../services/api'
import { PERMISSION_LABELS } from '../../auth/permissions'

const { Text } = Typography

const permissionOptions = Object.entries(PERMISSION_LABELS).map(([value, label]) => ({ value, label }))

type UserFormValues = {
  username?: string
  password?: string
  name?: string
  phone?: string
  email?: string
  is_active?: number
  is_admin?: number
  permissions?: PermissionKey[]
}

export default function UsersPage() {
  const [keyword, setKeyword] = useState('')
  const [isActive, setIsActive] = useState<number | undefined>()
  const [permission, setPermission] = useState<PermissionKey | undefined>()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ManagedUser | null>(null)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState<ManagedUser | null>(null)
  const [resetSaving, setResetSaving] = useState(false)
  const [form] = Form.useForm<UserFormValues>()
  const [resetForm] = Form.useForm<{ password: string }>()

  const { data: users, loading, refresh } = useRequest(
    () => listUsers({
      keyword: keyword || undefined,
      is_active: isActive,
      permission,
    }),
    { refreshDeps: [keyword, isActive, permission] },
  )

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ is_active: 1, is_admin: 0, permissions: [] })
    setModalOpen(true)
  }

  const openEdit = (row: ManagedUser) => {
    setEditing(row)
    form.setFieldsValue({
      username: row.username,
      name: row.name ?? undefined,
      phone: row.phone ?? undefined,
      email: row.email ?? undefined,
      is_active: row.is_active,
      is_admin: row.is_admin,
      permissions: row.permissions,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const payload: UpdateUserPayload = {
        name: values.name?.trim() || null,
        phone: values.phone?.trim() || null,
        email: values.email?.trim() || null,
        is_active: values.is_active ?? 1,
        is_admin: values.is_admin ?? 0,
        permissions: values.is_admin ? [] : (values.permissions ?? []),
      }
      if (editing) {
        await updateUser(editing.id, payload)
        message.success('用户已更新')
      } else {
        await createUser({
          ...payload,
          username: values.username!.trim(),
          password: values.password!,
        } as CreateUserPayload)
        message.success('用户已创建')
      }
      setModalOpen(false)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (row: ManagedUser) => {
    await updateUser(row.id, { is_active: row.is_active ? 0 : 1 })
    message.success(row.is_active ? '已停用' : '已启用')
    refresh()
  }

  const openReset = (row: ManagedUser) => {
    setResetting(row)
    resetForm.resetFields()
  }

  const handleResetPassword = async () => {
    if (!resetting) return
    const values = await resetForm.validateFields()
    setResetSaving(true)
    try {
      await resetUserPassword(resetting.id, values.password)
      message.success('密码已重置')
      setResetting(null)
    } finally {
      setResetSaving(false)
    }
  }

  const columns = useMemo(() => [
    { title: '用户名', dataIndex: 'username', width: 130, render: (v: string) => <Text strong>{v}</Text> },
    { title: '姓名', dataIndex: 'name', width: 120, render: (v: string | null) => v || '-' },
    { title: '联系方式', dataIndex: 'phone', width: 140, render: (v: string | null) => v || '-' },
    { title: '邮箱', dataIndex: 'email', width: 180, render: (v: string | null) => v || '-' },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      render: (v: number) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '账号类型',
      dataIndex: 'is_admin',
      width: 100,
      render: (v: number) => v ? <Tag color="red">管理员</Tag> : <Tag>普通用户</Tag>,
    },
    {
      title: '目录权限',
      dataIndex: 'permissions',
      render: (permissions: PermissionKey[], row: ManagedUser) => {
        if (row.is_admin) return <Text type="secondary">全部目录</Text>
        if (!permissions?.length) return <Text type="secondary">无目录权限</Text>
        return <Space size={4} wrap>{permissions.map(key => <Tag key={key} color="blue">{PERMISSION_LABELS[key]}</Tag>)}</Space>
      },
    },
    { title: '最后登录', dataIndex: 'last_login_at', width: 170, render: (v: string | null) => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', width: 170 },
    {
      title: '操作',
      width: 230,
      fixed: 'right' as const,
      render: (_: unknown, row: ManagedUser) => (
        <Space size={4} wrap>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => openReset(row)}>重置密码</Button>
          <Popconfirm
            title={row.is_active ? '确认停用该用户？' : '确认启用该用户？'}
            onConfirm={() => handleToggleActive(row)}
            okText="确认"
            cancelText="取消"
          >
            <Button size="small" danger={Boolean(row.is_active)}>{row.is_active ? '停用' : '启用'}</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [])

  return (
    <Card
      title="用户管理"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增用户</Button>}
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          allowClear
          placeholder="用户名 / 姓名 / 联系方式 / 邮箱"
          style={{ width: 280 }}
          onSearch={setKeyword}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 120 }}
          value={isActive}
          onChange={setIsActive}
          options={[{ value: 1, label: '启用' }, { value: 0, label: '停用' }]}
        />
        <Select
          allowClear
          placeholder="目录权限"
          style={{ width: 160 }}
          value={permission}
          onChange={setPermission}
          options={permissionOptions}
        />
      </Space>

      <Table
        rowKey="id"
        dataSource={users ?? []}
        columns={columns}
        loading={loading}
        scroll={{ x: 1300 }}
        pagination={{ pageSize: 20 }}
        size="small"
      />

      <Modal
        title={editing ? '编辑用户' : '新增用户'}
        open={modalOpen}
        onOk={handleSave}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input />
            </Form.Item>
          )}
          {editing && <Form.Item name="username" label="用户名"><Input disabled /></Form.Item>}
          {!editing && (
            <Form.Item name="password" label="初始密码" rules={[{ required: true, message: '请输入初始密码' }, { min: 6, message: '密码至少 6 位' }]}>
              <Input.Password />
            </Form.Item>
          )}
          <Form.Item name="name" label="姓名"><Input /></Form.Item>
          <Form.Item name="phone" label="联系方式"><Input /></Form.Item>
          <Form.Item name="email" label="邮箱"><Input /></Form.Item>
          <Form.Item name="is_active" label="状态" initialValue={1}>
            <Select options={[{ value: 1, label: '启用' }, { value: 0, label: '停用' }]} />
          </Form.Item>
          <Form.Item name="is_admin" label="账号类型" initialValue={0}>
            <Select options={[{ value: 0, label: '普通用户' }, { value: 1, label: '管理员' }]} />
          </Form.Item>
          <Form.Item shouldUpdate={(prev, cur) => prev.is_admin !== cur.is_admin} noStyle>
            {({ getFieldValue }) => getFieldValue('is_admin') ? (
              <Text type="secondary">管理员默认拥有全部目录权限。</Text>
            ) : (
              <Form.Item name="permissions" label="目录权限" initialValue={[]}>
                <Checkbox.Group options={permissionOptions} />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={resetting ? `重置密码：${resetting.username}` : '重置密码'}
        open={Boolean(resetting)}
        onOk={handleResetPassword}
        confirmLoading={resetSaving}
        onCancel={() => setResetting(null)}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={resetForm} layout="vertical">
          <Form.Item name="password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '密码至少 6 位' }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
