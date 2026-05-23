import { useEffect, useState } from 'react'
import {
  Tabs, Table, Button, Tag, Space, Modal, Form, Select,
  Input, InputNumber, Switch, message, Descriptions, Typography,
  Alert, Drawer
} from 'antd'
import {
  PlayCircleOutlined, PlusOutlined, EditOutlined, DeleteOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUploadFiles, listDispatchBatches, runDispatch,
  getDispatchBatchStats, listDispatchUnmatched, listDispatchRules,
  createDispatchRule, updateDispatchRule, deleteDispatchRule,
  type DispatchBatchStatsResponse, type DispatchCategoryStat, type DispatchRuleStat,
  type DispatchUnmatchedRow
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
interface DispatchRule {
  id: number; category_code: string; platform: string | null
  field: string; match_type: string; value: string
  item_name_keyword: string | null; priority: number; is_active: number
}

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
  { value: 'taobao', label: '淘宝' },
  { value: 'douyin', label: '抖音' },
]

const formatRuleDescription = (rule: DispatchRuleStat) => {
  if (!rule.field || !rule.match_type || !rule.value) return '规则已删除或不可用'
  const fieldLabel = FIELD_OPTIONS.find(o => o.value === rule.field)?.label ?? rule.field
  const matchTypeLabel = MATCH_TYPE_OPTIONS.find(o => o.value === rule.match_type)?.label ?? rule.match_type
  return `${fieldLabel} ${matchTypeLabel} ${rule.value}`
}

const formatPlatform = (platform: string | null) => (
  platform ? (PLATFORM_OPTIONS.find(o => o.value === platform)?.label ?? platform) : '不限'
)

const splitItemNameKeywords = (keyword: string | null) => (
  keyword?.split(/[,，、\n\r]+/).map(part => part.trim()).filter(Boolean) ?? []
)

const formatItemNameKeyword = (keyword: string | null) => {
  const keywords = splitItemNameKeywords(keyword)
  return keywords.length ? `商品名包含任一：${keywords.join(' / ')}` : '不限'
}

const normalizeRuleValues = (vals: Record<string, unknown>) => ({
  ...vals,
  platform: vals.platform || null,
  item_name_keyword: vals.item_name_keyword || null,
  is_active: vals.is_active ? 1 : 0,
})

const RuleFormItems = ({ categoryOptions }: { categoryOptions: { value: string; label: string }[] }) => (
  <>
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
    <Form.Item name="item_name_keyword" label="AND条件—商品名包含任一">
      <Input.TextArea
        autoSize={{ minRows: 1, maxRows: 3 }}
        placeholder="留空=不限；多个词用逗号、顿号或换行分隔"
      />
    </Form.Item>
    <Form.Item name="priority" label="优先级（数字越小越先）" rules={[{ required: true }]}>
      <InputNumber min={1} style={{ width: '100%' }} />
    </Form.Item>
    <Form.Item name="is_active" label="启用" valuePropName="checked">
      <Switch />
    </Form.Item>
  </>
)

// ─── Tab 1: 分发管理 ──────────────────────────────────────────
function DispatchManagementTab({ onRulesChanged }: { onRulesChanged: () => void }) {
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set())
  const [statsVisible, setStatsVisible] = useState(false)
  const [statsData, setStatsData] = useState<DispatchBatchStatsResponse | null>(null)
  const [currentStatsBatch, setCurrentStatsBatch] = useState<DispatchBatch | null>(null)
  const [unmatchedVisible, setUnmatchedVisible] = useState(false)
  const [unmatchedPage, setUnmatchedPage] = useState(1)
  const [unmatchedPageSize, setUnmatchedPageSize] = useState(20)
  const [unmatchedSearchInput, setUnmatchedSearchInput] = useState('')
  const [unmatchedKeyword, setUnmatchedKeyword] = useState('')
  const [editDrawerOpen, setEditDrawerOpen] = useState(false)
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null)
  const [ruleForm] = Form.useForm()
  const { options: categoryOptions } = useCategoryOptions()

  const { data: files } = useRequest(() => listUploadFiles().then(r => r.data as UploadFile[]))
  const { data: batches, refresh: refreshBatches } = useRequest(
    () => listDispatchBatches().then(r => r.data as DispatchBatch[])
  )
  const {
    data: unmatchedData,
    loading: unmatchedLoading,
  } = useRequest(
    () => currentStatsBatch
      ? listDispatchUnmatched(currentStatsBatch.id, {
        page: unmatchedPage,
        page_size: unmatchedPageSize,
        ...(unmatchedKeyword ? { keyword: unmatchedKeyword } : {}),
      }).then(r => r.data)
      : Promise.resolve({ total: 0, page: 1, page_size: unmatchedPageSize, items: [] }),
    {
      ready: unmatchedVisible && !!currentStatsBatch,
      refreshDeps: [currentStatsBatch?.id, unmatchedPage, unmatchedPageSize, unmatchedKeyword],
    }
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

  const refreshStats = async (batchId: number) => {
    const res = await getDispatchBatchStats(batchId)
    setStatsData(res.data)
  }

  const handleShowStats = async (batch: DispatchBatch) => {
    await refreshStats(batch.id)
    setCurrentStatsBatch(batch)
    setStatsVisible(true)
  }

  const openUnmatchedModal = () => {
    setUnmatchedPage(1)
    setUnmatchedSearchInput('')
    setUnmatchedKeyword('')
    setUnmatchedVisible(true)
  }

  const formatCategoryPath = (row: DispatchUnmatchedRow) => (
    [row.category_lv1, row.category_lv2, row.category_lv3].filter(Boolean).join(' / ') || '-'
  )

  const canEditRuleStat = (rule: DispatchRuleStat) => (
    rule.rule_id != null && !!rule.field && !!rule.match_type && !!rule.value && !!rule.category_code
  )

  const openRuleEdit = (rule: DispatchRuleStat) => {
    setEditingRuleId(rule.rule_id)
    ruleForm.setFieldsValue({
      category_code: rule.category_code,
      platform: rule.platform,
      field: rule.field,
      match_type: rule.match_type,
      value: rule.value,
      item_name_keyword: rule.item_name_keyword,
      priority: rule.priority ?? 100,
      is_active: rule.is_active !== 0,
    })
    setEditDrawerOpen(true)
  }

  const handleRuleEditSubmit = async () => {
    if (!editingRuleId) return
    const vals = await ruleForm.validateFields()
    await updateDispatchRule(editingRuleId, normalizeRuleValues(vals))
    setEditDrawerOpen(false)
    if (currentStatsBatch) await refreshStats(currentStatsBatch.id)
    onRulesChanged()
    message.success('规则已保存，重新分发后对分发结果生效。')
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
        width={960}
      >
        {statsData && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="总行数">{statsData.total_rows}</Descriptions.Item>
              <Descriptions.Item label="已分发">{statsData.dispatched_rows}</Descriptions.Item>
              <Descriptions.Item label="未命中">
                {statsData.unmatched_rows && statsData.unmatched_rows > 0 ? (
                  <Button type="link" size="small" style={{ padding: 0 }} onClick={openUnmatchedModal}>
                    {statsData.unmatched_rows} 条
                  </Button>
                ) : (
                  `${statsData.unmatched_rows ?? 0} 条`
                )}
              </Descriptions.Item>
            </Descriptions>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="规则内容为当前配置；历史批次命中关系基于分发时的规则 ID。修改规则后需重新分发才会改变命中结果。"
            />
            <Table<DispatchCategoryStat>
              size="small"
              rowKey={row => row.category_code || 'unknown'}
              dataSource={statsData.categories}
              pagination={false}
              expandable={{
                rowExpandable: category => statsData.rules.some(rule => rule.category_code === category.category_code),
                expandedRowRender: category => (
                  <Table<DispatchRuleStat>
                    size="small"
                    rowKey={(row, index) => `${row.rule_id ?? 'missing'}-${row.category_code ?? 'none'}-${index}`}
                    dataSource={statsData.rules.filter(rule => rule.category_code === category.category_code)}
                    pagination={false}
                    columns={[
                      { title: '规则', render: (_: unknown, row) => formatRuleDescription(row) },
                      {
                        title: 'AND 条件', width: 160, dataIndex: 'item_name_keyword',
                        render: (v: string | null) => formatItemNameKeyword(v)
                      },
                      { title: '平台', width: 90, dataIndex: 'platform', render: (v: string | null) => formatPlatform(v) },
                      { title: '优先级', width: 90, dataIndex: 'priority', render: (v: number | null) => v ?? '-' },
                      { title: '命中数量', width: 100, dataIndex: 'count' },
                      {
                        title: '操作', width: 80,
                        render: (_: unknown, row) => canEditRuleStat(row)
                          ? <Button type="link" size="small" onClick={() => openRuleEdit(row)}>编辑</Button>
                          : null
                      },
                    ]}
                  />
                ),
              }}
              columns={[
                { title: '品类', dataIndex: 'category_name', render: (v: string | null) => v || '未知品类' },
                { title: '品类编码', dataIndex: 'category_code', width: 160 },
                { title: '行数', dataIndex: 'count', width: 120 },
              ]}
            />
          </>
        )}
      </Modal>
      <Modal
        title="未识别明细"
        open={unmatchedVisible}
        onCancel={() => setUnmatchedVisible(false)}
        footer={null}
        width={1200}
      >
        <Input.Search
          allowClear
          value={unmatchedSearchInput}
          placeholder="搜索商品ID / 商品名称"
          style={{ width: 320, marginBottom: 12 }}
          onChange={e => setUnmatchedSearchInput(e.target.value)}
          onSearch={value => {
            setUnmatchedKeyword(value.trim())
            setUnmatchedPage(1)
          }}
        />
        <Table<DispatchUnmatchedRow>
          size="small"
          rowKey="id"
          loading={unmatchedLoading}
          dataSource={unmatchedData?.items ?? []}
          scroll={{ x: 1100 }}
          pagination={{
            current: unmatchedData?.page ?? unmatchedPage,
            pageSize: unmatchedData?.page_size ?? unmatchedPageSize,
            total: unmatchedData?.total ?? 0,
            showSizeChanger: true,
            showTotal: total => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setUnmatchedPage(page)
              setUnmatchedPageSize(pageSize)
            },
          }}
          columns={[
            { title: '商品ID', dataIndex: 'item_id', width: 120, render: (v: string | null) => v || '-' },
            { title: '商品名称', dataIndex: 'item_name', width: 220, ellipsis: true, render: (v: string | null) => v || '-' },
            { title: '平台', dataIndex: 'platform', width: 80, render: (v: string | null) => v || '-' },
            { title: '月份', dataIndex: 'month', width: 80, render: (v: number | null) => v ?? '-' },
            { title: '类目层级', width: 220, render: (_: unknown, row) => formatCategoryPath(row) },
            { title: '品牌原始值', dataIndex: 'brand_raw', width: 120, render: (v: string | null) => v || '-' },
            { title: '店铺名', dataIndex: 'shop_name', width: 140, ellipsis: true, render: (v: string | null) => v || '-' },
            { title: '价格', dataIndex: 'price', width: 90, render: (v: number | null) => v ?? '-' },
            { title: '销量', dataIndex: 'sales_qty', width: 90, render: (v: number | null) => v ?? '-' },
            { title: '销额', dataIndex: 'sales_amount', width: 100, render: (v: number | null) => v ?? '-' },
          ]}
        />
      </Modal>
      <Drawer
        title="编辑规则"
        open={editDrawerOpen}
        onClose={() => setEditDrawerOpen(false)}
        width={420}
        extra={(
          <Space>
            <Button onClick={() => setEditDrawerOpen(false)}>取消</Button>
            <Button type="primary" onClick={handleRuleEditSubmit}>保存</Button>
          </Space>
        )}
      >
        <Form form={ruleForm} layout="vertical">
          <RuleFormItems categoryOptions={categoryOptions} />
        </Form>
      </Drawer>
    </>
  )
}

// ─── Tab 2: 分发规则 ──────────────────────────────────────────
function DispatchRulesTab({ refreshVersion }: { refreshVersion: number }) {
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

  useEffect(() => {
    if (refreshVersion > 0) refresh()
  }, [refreshVersion, refresh])

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
    const payload = normalizeRuleValues(vals)
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

  const sortedRules = [...(rules ?? [])].sort((a, b) => (
    a.category_code.localeCompare(b.category_code) || a.priority - b.priority || a.id - b.id
  ))

  const columns = [
    {
      title: '品类', dataIndex: 'category_code', width: 100,
      sorter: (a: DispatchRule, b: DispatchRule) => a.category_code.localeCompare(b.category_code),
      defaultSortOrder: 'ascend' as const,
    },
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
    { title: 'AND条件', dataIndex: 'item_name_keyword', width: 180, render: (v: string | null) => formatItemNameKeyword(v) },
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
          placeholder="平台筛选" allowClear showSearch optionFilterProp="label" style={{ width: 120 }}
          options={PLATFORM_OPTIONS}
          onChange={v => setFilterPlatform(v || undefined)}
        />
        <Select
          placeholder="品类筛选" allowClear showSearch optionFilterProp="label" style={{ width: 140 }}
          options={categoryOptions}
          onChange={v => setFilterCategory(v || undefined)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
      </Space>
      <Table rowKey="id" dataSource={sortedRules} columns={columns} size="small" pagination={{ pageSize: 20 }} />

      <Modal
        title={editingId ? '编辑规则' : '新增规则'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={520}
      >
        <Form form={form} layout="vertical">
          <RuleFormItems categoryOptions={categoryOptions} />
        </Form>
      </Modal>
    </>
  )
}

// ─── 主页面 ───────────────────────────────────────────────────
export default function DispatchPage() {
  const [rulesRefreshVersion, setRulesRefreshVersion] = useState(0)
  const notifyRulesChanged = () => setRulesRefreshVersion(v => v + 1)

  return (
    <Tabs
      items={[
        { key: 'management', label: '分发管理', children: <DispatchManagementTab onRulesChanged={notifyRulesChanged} /> },
        { key: 'rules', label: '分发规则', children: <DispatchRulesTab refreshVersion={rulesRefreshVersion} /> },
      ]}
    />
  )
}
