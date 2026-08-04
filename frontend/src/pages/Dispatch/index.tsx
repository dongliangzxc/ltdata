import { useEffect, useMemo, useState } from 'react'
import {
  Tabs, Table, Button, Tag, Space, Modal, Form, Select,
  Input, InputNumber, Switch, message, Descriptions, Typography,
  Alert, Drawer, Progress, Popconfirm
} from 'antd'
import {
  PlayCircleOutlined, PlusOutlined, EditOutlined, DeleteOutlined, DownloadOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import dayjs from 'dayjs'
import {
  listUploadFiles, listDispatchBatches, runDispatch, enqueueDispatchCategoryForClean,
  getDispatchBatchStats, listDispatchUnmatched, listDispatchRules,
  createDispatchRule, updateDispatchRule, deleteDispatchRule,
  createDispatchExportJob, listDispatchExportJobs, deleteDispatchExportJob, downloadDispatchExport,
  type DispatchBatchStatsResponse, type DispatchCategoryStat, type DispatchRuleStat,
  type DispatchExportJob, type DispatchUnmatchedRow
} from '../../services/api'
import { useCategoryOptions, type CategoryOption } from '../../hooks/useCategoryOptions'
import { useAuth } from '../../auth/AuthContext'

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

const formatMonth = (value: number) => `${String(value).slice(0, 4)}-${String(value).slice(4)}`

const formatMonths = (values?: number[] | null, fallback?: number | null) => {
  const months = values && values.length > 0 ? values : fallback ? [fallback] : []
  return months.map(formatMonth).join(', ')
}

const formatDataPlatform = (platform: string | null) => (
  platform ? (PLATFORM_OPTIONS.find(o => o.value === platform)?.label ?? platform) : '未知平台'
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

const RuleFormItems = ({ categoryOptions }: { categoryOptions: CategoryOption[] }) => (
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

function useVisibleCategories() {
  const { user } = useAuth()
  const { options: categoryOptions, loading } = useCategoryOptions()
  const categoryPermissions = user?.category_permissions ?? []
  const visibleCategories = useMemo(
    () => categoryPermissions.length === 0
      ? categoryOptions
      : categoryOptions.filter(category => categoryPermissions.includes(category.value)),
    [categoryOptions, categoryPermissions],
  )

  return { visibleCategories, loading }
}

// ─── Tab 1: 分发管理 ──────────────────────────────────────────
function DispatchManagementTab({ onRulesChanged, visibleCategories }: { onRulesChanged: () => void; visibleCategories: CategoryOption[] }) {
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set())
  const [runningCategoryKeys, setRunningCategoryKeys] = useState<Set<string>>(new Set())
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
  const visibleCategoryCodes = useMemo(
    () => new Set(visibleCategories.map(category => category.value)),
    [visibleCategories],
  )

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

  const handleRunCategory = async (category: DispatchCategoryStat) => {
    if (!currentStatsBatch) return
    const key = `${currentStatsBatch.id}-${category.category_code}`
    setRunningCategoryKeys(prev => new Set(prev).add(key))
    try {
      const res = await enqueueDispatchCategoryForClean(currentStatsBatch.id, category.category_code)
      const queuedText = res.data.queued_count > 0 ? `，已入任务 ${res.data.queued_count} 条` : ''
      message.success(`${category.category_name || category.category_code} 分发成功：分发结果 ${res.data.dispatch_count} 条，新增待入队 ${res.data.pending_count} 条${queuedText}`)
    } finally {
      setRunningCategoryKeys(prev => { const s = new Set(prev); s.delete(key); return s })
    }
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

  const visibleStatsCategories = useMemo(
    () => statsData?.categories.filter(category => visibleCategoryCodes.has(category.category_code)) ?? [],
    [statsData, visibleCategoryCodes],
  )
  const visibleStatsRules = useMemo(
    () => statsData?.rules.filter(rule => !!rule.category_code && visibleCategoryCodes.has(rule.category_code)) ?? [],
    [statsData, visibleCategoryCodes],
  )

  const canEditRuleStat = (rule: DispatchRuleStat) => (
    rule.rule_id != null
      && !!rule.field
      && !!rule.match_type
      && !!rule.value
      && !!rule.category_code
      && visibleCategoryCodes.has(rule.category_code)
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
              {batch.finished_at || '-'}
            </Text>
          </Space>
        )
      }
    },
    {
      title: '操作', width: 260,
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
              <>
                <Button type="link" size="small" onClick={() => handleShowStats(batch)}>
                  查看明细
                </Button>
              </>
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
              <Descriptions.Item label="分发结果数">{statsData.dispatched_rows}</Descriptions.Item>
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
              message="同一原始行可分发到多个类目；分发结果数可能大于总行数。同一类目命中多条规则时只记录优先级最高的规则。规则内容为当前配置，修改规则后需重新分发才会改变命中结果。"
            />
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="分发完成后，命中的数据会进入清洗任务页的待入清洗队列。请在清洗任务页按品类、平台和月份创建或追加清洗任务。"
            />
            <Table<DispatchCategoryStat>
              size="small"
              rowKey={row => row.category_code || 'unknown'}
              dataSource={visibleStatsCategories}
              pagination={false}
              expandable={{
                rowExpandable: category => visibleStatsRules.some(rule => rule.category_code === category.category_code),
                expandedRowRender: category => (
                  <Table<DispatchRuleStat>
                    size="small"
                    rowKey={(row, index) => `${row.rule_id ?? 'missing'}-${row.category_code ?? 'none'}-${index}`}
                    dataSource={visibleStatsRules.filter(rule => rule.category_code === category.category_code)}
                    pagination={false}
                    columns={[
                      { title: '规则', render: (_: unknown, row) => formatRuleDescription(row) },
                      {
                        title: 'AND 条件', width: 160, dataIndex: 'item_name_keyword',
                        render: (v: string | null) => formatItemNameKeyword(v)
                      },
                      { title: '平台', width: 90, dataIndex: 'platform', render: (v: string | null) => formatPlatform(v) },
                      { title: '优先级', width: 90, dataIndex: 'priority', render: (v: number | null) => v ?? '-' },
                      { title: '规则命中', width: 100, dataIndex: 'count' },
                      { title: '分发归因', width: 100, dataIndex: 'assigned_count', render: (v: number | undefined) => v ?? '-' },
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
                { title: '行数', dataIndex: 'count', width: 100 },
                {
                  title: '平台分布', width: 220,
                  render: (_: unknown, row) => {
                    const platforms = row.platforms ?? []
                    if (!platforms.length) return <Text type="secondary">-</Text>
                    return (
                      <Space size={[4, 4]} wrap>
                        {platforms.map(item => (
                          <Tag key={item.platform ?? 'unknown'} color="blue">
                            {formatDataPlatform(item.platform)} {item.count}
                          </Tag>
                        ))}
                      </Space>
                    )
                  }
                },
                {
                  title: '操作', width: 120,
                  render: (_: unknown, row: DispatchCategoryStat) => {
                    const key = currentStatsBatch ? `${currentStatsBatch.id}-${row.category_code}` : row.category_code
                    return (
                      <Popconfirm
                        title="加入待入清洗队列"
                        description={`将当前批次下的 ${row.category_name || row.category_code} 数据加入待入清洗队列？不会改变当前分发明细。`}
                        okText="确认"
                        cancelText="取消"
                        onConfirm={() => handleRunCategory(row)}
                      >
                        <Button type="link" size="small" loading={runningCategoryKeys.has(key)}>
                          分发
                        </Button>
                      </Popconfirm>
                    )
                  },
                },
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
          <RuleFormItems categoryOptions={visibleCategories} />
        </Form>
      </Drawer>
    </>
  )
}

// ─── Tab 2: 分发结果下载 ──────────────────────────────────────
function DispatchExportTab({ visibleCategories }: { visibleCategories: CategoryOption[] }) {
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [platform, setPlatform] = useState<string | undefined>()
  const [months, setMonths] = useState<number[]>([])
  const [exporting, setExporting] = useState(false)
  const [downloadingToken, setDownloadingToken] = useState<string | null>(null)
  const [exportJobsPage, setExportJobsPage] = useState(1)
  const [exportJobsPageSize, setExportJobsPageSize] = useState(50)
  const categoryOptions = visibleCategories
  const visibleCategoryCodes = useMemo(
    () => new Set(categoryOptions.map(category => category.value)),
    [categoryOptions],
  )
  const { data: exportJobsData, loading: exportJobsLoading, refresh: refreshExportJobs } = useRequest(
    () => listDispatchExportJobs({ page: exportJobsPage, page_size: exportJobsPageSize }),
    { pollingInterval: 10000, refreshDeps: [exportJobsPage, exportJobsPageSize] }
  )
  const exportJobs = useMemo(
    () => (exportJobsData?.data.items ?? []).filter(job => !!job.category_code && visibleCategoryCodes.has(job.category_code)),
    [exportJobsData, visibleCategoryCodes],
  )
  useEffect(() => {
    if (categoryCode && !visibleCategoryCodes.has(categoryCode)) {
      setCategoryCode(undefined)
    }
  }, [categoryCode, visibleCategoryCodes])
  const exportJobsInitialLoading = exportJobsLoading && !exportJobsData

  const refreshFirstExportJobsPage = () => {
    if (exportJobsPage === 1) {
      refreshExportJobs()
    } else {
      setExportJobsPage(1)
    }
  }

  const handleExport = async () => {
    if (!categoryCode && !platform && months.length === 0) {
      message.warning('请至少选择品类、平台或月份后再创建导出任务')
      return
    }
    setExporting(true)
    try {
      await createDispatchExportJob({ category_code: categoryCode, platform, months })
      message.success('导出任务已创建，可在列表查看进度')
      refreshFirstExportJobsPage()
    } catch {
      // API interceptor already shows the backend error message.
    } finally {
      setExporting(false)
    }
  }

  const handleDeleteExportJob = async (jobId: number) => {
    try {
      await deleteDispatchExportJob(jobId)
      message.success('已删除')
      refreshFirstExportJobsPage()
    } catch {
      // API interceptor already shows the backend error message.
    }
  }

  const handleDownloadExportJob = async (downloadUrl: string, filename?: string | null) => {
    const tokenPrefix = '/api/dispatch/export/download/'
    if (!downloadUrl.startsWith(tokenPrefix)) {
      message.error('导出失败，下载链接不合法')
      return
    }
    const token = downloadUrl.slice(tokenPrefix.length)
    if (!token) {
      message.error('导出失败，未返回下载链接')
      return
    }

    setDownloadingToken(token)
    try {
      const response = await downloadDispatchExport(token)
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const a = document.createElement('a')
      document.body.appendChild(a)
      a.href = url
      a.download = filename || 'dispatch_export.xlsx'
      a.click()
      document.body.removeChild(a)
      setTimeout(() => window.URL.revokeObjectURL(url), 100)
    } catch {
      message.error('导出失败，请重试')
    } finally {
      setDownloadingToken(null)
    }
  }

  const statusMeta: Record<DispatchExportJob['status'], { label: string; color: string }> = {
    pending: { label: '等待中', color: 'default' },
    running: { label: '导出中', color: 'processing' },
    done: { label: '已完成', color: 'success' },
    error: { label: '失败', color: 'error' },
  }

  const exportJobColumns = [
    { title: '任务ID', dataIndex: 'job_id', width: 90 },
    {
      title: '月份', dataIndex: 'months', width: 180,
      render: (values: number[] | null, row: DispatchExportJob) => {
        const text = formatMonths(values, row.month)
        return text || <Text type="secondary">不限</Text>
      }
    },
    {
      title: '品类', dataIndex: 'category_code', width: 150,
      render: (value: string | null) => value ? (categoryOptions.find(option => option.value === value)?.label ?? value) : <Text type="secondary">不限</Text>
    },
    {
      title: '平台', dataIndex: 'platform', width: 100,
      render: (value: string | null) => value ? <Tag color="blue">{formatPlatform(value)}</Tag> : <Text type="secondary">不限</Text>
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (value: DispatchExportJob['status']) => {
        const meta = statusMeta[value] ?? { label: value, color: 'default' }
        return <Tag color={meta.color}>{meta.label}</Tag>
      }
    },
    {
      title: '进度', dataIndex: 'progress', width: 180,
      render: (value: number, row: DispatchExportJob) => (
        <Progress percent={value ?? 0} size="small" status={row.status === 'error' ? 'exception' : row.status === 'done' ? 'success' : 'active'} />
      )
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 170,
      render: (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'
    },
    {
      title: '下载人', dataIndex: 'downloaders', width: 220,
      render: (value: string[] | null) => {
        const downloaders = Array.isArray(value) ? value.filter(Boolean) : []
        return downloaders.length ? downloaders.join('、') : <Text type="secondary">—</Text>
      }
    },
    {
      title: '文件名', dataIndex: 'filename', ellipsis: true,
      render: (value: string | null) => value || <Text type="secondary">生成中</Text>
    },
    {
      title: '操作', key: 'action', width: 220, fixed: 'right' as const,
      render: (_: unknown, row: DispatchExportJob) => (
        <Space>
          <Button size="small" onClick={refreshExportJobs}>刷新</Button>
          {row.status === 'done' && row.download_url && (() => {
            const downloadToken = row.download_url.slice('/api/dispatch/export/download/'.length)
            return (
              <Button size="small" type="link" icon={<DownloadOutlined />} loading={downloadingToken === downloadToken} onClick={() => handleDownloadExportJob(row.download_url as string, row.filename)}>下载</Button>
            )
          })()}
          {row.status === 'error' && row.error_msg && (
            <Button size="small" type="link" danger onClick={() => Modal.error({ title: '导出失败', content: row.error_msg })}>原因</Button>
          )}
          <Popconfirm
            title="确认删除该下载记录？"
            description="将同步删除已生成的导出文件，旧下载链接将不可用。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => handleDeleteExportJob(row.job_id)}
          >
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="按品类和平台下载当前分发结果池。系统会按每个上传文件的最新已完成分发批次取数，多个文件命中的数据会串联导出。"
      />
      <Space wrap>
        <Select
          mode="multiple"
          allowClear
          showSearch
          placeholder="选择月份"
          style={{ width: 220 }}
          value={months}
          optionFilterProp="label"
          maxTagCount="responsive"
          options={Array.from({ length: 36 }, (_, index) => {
            const value = Number(dayjs().subtract(index, 'month').format('YYYYMM'))
            return { value, label: formatMonth(value) }
          })}
          onChange={(values) => setMonths([...values].sort((a, b) => a - b))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="选择品类"
          style={{ width: 220 }}
          value={categoryCode}
          onChange={setCategoryCode}
          options={categoryOptions}
        />
        <Select
          allowClear
          placeholder="选择平台"
          style={{ width: 160 }}
          value={platform}
          onChange={setPlatform}
          options={PLATFORM_OPTIONS}
        />
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={handleExport}
        >
          创建导出任务
        </Button>
      </Space>
      <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
        至少选择品类、平台或月份后再导出；月份按原始数据月份 YYYYMM 筛选；如导出范围内包含多个上传模板，会按模板分 Sheet。
      </Text>
      <div style={{ marginTop: 24 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
          <Text strong>导出任务列表</Text>
          <Button onClick={refreshExportJobs} loading={exportJobsInitialLoading}>刷新列表</Button>
        </Space>
        <Table
          rowKey="job_id"
          size="small"
          bordered
          loading={exportJobsInitialLoading}
          columns={exportJobColumns}
          dataSource={exportJobs}
          pagination={{
            current: exportJobsPage,
            pageSize: exportJobsPageSize,
            total: exportJobs.length,
            showSizeChanger: true,
            showTotal: total => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setExportJobsPage(page)
              setExportJobsPageSize(pageSize)
            },
          }}
          scroll={{ x: 1320 }}
          locale={{ emptyText: '暂无导出任务' }}
        />
      </div>
    </>
  )
}

// ─── Tab 3: 分发规则 ──────────────────────────────────────────
function DispatchRulesTab({ refreshVersion, visibleCategories }: { refreshVersion: number; visibleCategories: CategoryOption[] }) {
  const [filterPlatform, setFilterPlatform] = useState<string | undefined>()
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const categoryOptions = visibleCategories
  const visibleCategoryCodes = useMemo(
    () => new Set(categoryOptions.map(category => category.value)),
    [categoryOptions],
  )

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

  useEffect(() => {
    if (filterCategory && !visibleCategoryCodes.has(filterCategory)) {
      setFilterCategory(undefined)
    }
  }, [filterCategory, visibleCategoryCodes])

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

  const visibleRules = useMemo(
    () => (rules ?? []).filter(rule => visibleCategoryCodes.has(rule.category_code)),
    [rules, visibleCategoryCodes],
  )
  const sortedRules = [...visibleRules].sort((a, b) => (
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
      render: (_: unknown, row: DispatchRule) => visibleCategoryCodes.has(row.category_code) ? (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => Modal.confirm({ title: '确认删除该规则？', onOk: () => handleDelete(row.id) })}>
            删除
          </Button>
        </Space>
      ) : null
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
      <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        共 {sortedRules.length} 条规则
      </Text>

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
  const { visibleCategories, loading } = useVisibleCategories()

  if (loading) {
    return <Alert type="info" showIcon message="正在加载可用品类" />
  }

  if (visibleCategories.length === 0) {
    return (
      <Alert
        type="warning"
        showIcon
        message="暂无可用品类"
        description="当前账号未配置 category_permissions，无法查看分发页面中的分类内容。"
      />
    )
  }

  return (
    <Tabs
      items={[
        { key: 'management', label: '分发管理', children: <DispatchManagementTab onRulesChanged={notifyRulesChanged} visibleCategories={visibleCategories} /> },
        { key: 'export', label: '分发结果下载', children: <DispatchExportTab visibleCategories={visibleCategories} /> },
        { key: 'rules', label: '分发规则', children: <DispatchRulesTab refreshVersion={rulesRefreshVersion} visibleCategories={visibleCategories} /> },
      ]}
    />
  )
}
