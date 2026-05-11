import { useState } from 'react'
import {
  Tabs, Table, Button, Tag, Space, Modal, Form, Select,
  Input, InputNumber, Switch, message, Descriptions, Typography
} from 'antd'
import {
  PlayCircleOutlined, PlusOutlined, EditOutlined, DeleteOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUploadFiles, listDispatchBatches, runDispatch,
  getDispatchBatchStats, listDispatchRules,
  createDispatchRule, updateDispatchRule, deleteDispatchRule
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

const { Text } = Typography

// ─── Types ───────────────────────────────────────────────────
interface UploadFile {
  id: number; filename: string; platform: string; month_range: string; row_count: number
}
interface DispatchBatch {
  id: number; file_id: number; status: string
  total_rows: number | null; dispatched_rows: number | null; unmatched_rows: number | null
  created_at: string; finished_at: string | null
}
interface CategoryStat { category_code: string; count: number }
interface DispatchRule {
  id: number; category_code: string; platform: string | null
  field: string; match_type: string; value: string
  item_name_keyword: string | null; priority: number; is_active: number
}

// ─── Tab 1: 分发管理 ──────────────────────────────────────────
function DispatchManagementTab() {
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set())
  const [statsVisible, setStatsVisible] = useState(false)
  const [statsData, setStatsData] = useState<{ batch: DispatchBatch; categories: CategoryStat[] } | null>(null)

  const { data: files } = useRequest(() => listUploadFiles().then(r => r.data as UploadFile[]))
  const { data: batches, refresh: refreshBatches } = useRequest(
    () => listDispatchBatches().then(r => r.data as DispatchBatch[])
  )

  // 构建 file_id → latest done batch 映射
  const batchByFile = (batches ?? []).reduce<Record<number, DispatchBatch>>((acc, b) => {
    if (b.status === 'done') {
      if (!acc[b.file_id] || b.id > acc[b.file_id].id) acc[b.file_id] = b
    }
    return acc
  }, {})

  const handleRun = async (fileId: number) => {
    setRunningIds(prev => new Set(prev).add(fileId))
    try {
      await runDispatch(fileId)
      message.success('分发完成')
      refreshBatches()
    } finally {
      setRunningIds(prev => { const s = new Set(prev); s.delete(fileId); return s })
    }
  }

  const handleShowStats = async (batch: DispatchBatch) => {
    const res = await getDispatchBatchStats(batch.id)
    setStatsData({ batch, categories: res.data.categories })
    setStatsVisible(true)
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string) => <Tag color="blue">{v}</Tag>
    },
    { title: '月份范围', dataIndex: 'month_range', width: 120 },
    { title: '数据量', dataIndex: 'row_count', width: 80 },
    {
      title: '分发状态', width: 180,
      render: (_: unknown, row: UploadFile) => {
        const batch = batchByFile[row.id]
        if (runningIds.has(row.id)) return <Tag color="processing">分发中...</Tag>
        if (!batch) return <Tag>未分发</Tag>
        return (
          <Space direction="vertical" size={0}>
            <Tag color="green">已分发</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {new Date(batch.finished_at!).toLocaleString('zh-CN')}
            </Text>
          </Space>
        )
      }
    },
    {
      title: '操作', width: 160,
      render: (_: unknown, row: UploadFile) => {
        const batch = batchByFile[row.id]
        return (
          <Space>
            <Button
              type="link" size="small" icon={<PlayCircleOutlined />}
              loading={runningIds.has(row.id)}
              onClick={() => handleRun(row.id)}
            >
              {batch ? '重新分发' : '执行分发'}
            </Button>
            {batch && (
              <Button type="link" size="small" onClick={() => handleShowStats(batch)}>
                查看明细
              </Button>
            )}
          </Space>
        )
      }
    },
  ]

  return (
    <>
      <Table
        rowKey="id"
        dataSource={files ?? []}
        columns={columns}
        size="small"
        pagination={{ pageSize: 20 }}
      />
      <Modal
        title="分发明细"
        open={statsVisible}
        onCancel={() => setStatsVisible(false)}
        footer={null}
        width={480}
      >
        {statsData && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="总行数">{statsData.batch.total_rows}</Descriptions.Item>
              <Descriptions.Item label="已分发">{statsData.batch.dispatched_rows}</Descriptions.Item>
              <Descriptions.Item label="未命中">{statsData.batch.unmatched_rows}</Descriptions.Item>
            </Descriptions>
            <Table
              size="small"
              rowKey="category_code"
              dataSource={statsData.categories}
              pagination={false}
              columns={[
                { title: '品类', dataIndex: 'category_code' },
                { title: '行数', dataIndex: 'count', width: 80 },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  )
}

// ─── Tab 2: 分发规则 ──────────────────────────────────────────
const FIELD_OPTIONS = [
  { value: 'category_lv0', label: 'Lv0类目' },
  { value: 'category_lv1', label: 'Lv1类目' },
  { value: 'category_lv2', label: 'Lv2类目' },
  { value: 'category_lv3', label: 'Lv3类目' },
  { value: 'item_name', label: '商品名称' },
]
const MATCH_TYPE_OPTIONS = [
  { value: 'contains', label: '包含' },
  { value: 'equals', label: '精准' },
]
const PLATFORM_OPTIONS = [
  { value: 'jd', label: '京东' },
  { value: 'tmall', label: '天猫' },
]

function DispatchRulesTab() {
  const [filterPlatform, setFilterPlatform] = useState<string | undefined>()
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const { options: categoryOptions } = useCategoryOptions()

  const { data: rules, refresh } = useRequest(
    () => listDispatchRules({
      ...(filterPlatform ? { platform: filterPlatform } : {}),
      ...(filterCategory ? { category_code: filterCategory } : {}),
    }).then(r => r.data as DispatchRule[]),
    { refreshDeps: [filterPlatform, filterCategory] }
  )

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    form.setFieldsValue({ priority: 100, is_active: true })
    setModalOpen(true)
  }

  const openEdit = (rule: DispatchRule) => {
    setEditingId(rule.id)
    form.setFieldsValue({ ...rule, is_active: rule.is_active === 1 })
    setModalOpen(true)
  }

  const handleDelete = async (id: number) => {
    await deleteDispatchRule(id)
    message.success('已删除')
    refresh()
  }

  const handleSubmit = async () => {
    const vals = await form.validateFields()
    const payload = { ...vals, platform: vals.platform || null, item_name_keyword: vals.item_name_keyword || null }
    if (editingId) {
      await updateDispatchRule(editingId, payload)
      message.success('已更新')
    } else {
      await createDispatchRule(payload)
      message.success('已新增')
    }
    setModalOpen(false)
    refresh()
  }

  const columns = [
    { title: '品类', dataIndex: 'category_code', width: 100 },
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string | null) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">不限</Text>
    },
    {
      title: '字段', dataIndex: 'field', width: 100,
      render: (v: string) => FIELD_OPTIONS.find(o => o.value === v)?.label ?? v
    },
    {
      title: '匹配方式', dataIndex: 'match_type', width: 80,
      render: (v: string) => MATCH_TYPE_OPTIONS.find(o => o.value === v)?.label ?? v
    },
    { title: '匹配值', dataIndex: 'value' },
    { title: 'AND条件', dataIndex: 'item_name_keyword', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '优先级', dataIndex: 'priority', width: 70 },
    {
      title: '启用', dataIndex: 'is_active', width: 60,
      render: (v: number) => <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>
    },
    {
      title: '操作', width: 100,
      render: (_: unknown, row: DispatchRule) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => Modal.confirm({ title: '确认删除该规则？', onOk: () => handleDelete(row.id) })}>
            删除
          </Button>
        </Space>
      )
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="平台筛选" allowClear style={{ width: 120 }}
          options={PLATFORM_OPTIONS}
          onChange={v => setFilterPlatform(v || undefined)}
        />
        <Select
          placeholder="品类筛选" allowClear style={{ width: 140 }}
          options={categoryOptions}
          onChange={v => setFilterCategory(v || undefined)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
      </Space>
      <Table rowKey="id" dataSource={rules ?? []} columns={columns} size="small" pagination={{ pageSize: 20 }} />

      <Modal
        title={editingId ? '编辑规则' : '新增规则'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="category_code" label="目标品类" rules={[{ required: true }]}>
            <Select options={categoryOptions} placeholder="选择品类" />
          </Form.Item>
          <Form.Item name="platform" label="平台限定">
            <Select options={PLATFORM_OPTIONS} allowClear placeholder="不限" />
          </Form.Item>
          <Form.Item name="field" label="匹配字段" rules={[{ required: true }]}>
            <Select options={FIELD_OPTIONS} />
          </Form.Item>
          <Form.Item name="match_type" label="匹配方式" rules={[{ required: true }]}>
            <Select options={MATCH_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="value" label="匹配值" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="item_name_keyword" label="AND条件—商品名包含">
            <Input placeholder="留空=不限" />
          </Form.Item>
          <Form.Item name="priority" label="优先级（数字越小越先）" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ─── 主页面 ───────────────────────────────────────────────────
export default function DispatchPage() {
  return (
    <Tabs
      items={[
        { key: 'management', label: '分发管理', children: <DispatchManagementTab /> },
        { key: 'rules', label: '分发规则', children: <DispatchRulesTab /> },
      ]}
    />
  )
}
