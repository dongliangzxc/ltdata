import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Collapse, Progress, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import {
  getPlatformStatsOverview,
  getPlatformStatsProgress,
  type PlatformStatsOverview,
  type PlatformStatsProgress,
} from '../../services/api'

const { Text } = Typography

type CategoryRow = PlatformStatsOverview['categories'][number]
type MonthlyRow = PlatformStatsOverview['monthly'][number]
type SourceRow = PlatformStatsOverview['sources'][number]
type ProgressRow = PlatformStatsProgress['categories'][number]

const platformLabelMap: Record<string, string> = {
  jd: '京东',
  tmall: '天猫',
  taobao: '淘宝',
  douyin: '抖音',
  amazon: '亚马逊',
  shopee: '虾皮',
}

const sourceLabelMap: Record<string, string> = {
  s0: 'URL 映射',
  's0.2': '历史库',
  historical: '历史库',
  's0.5': '显式规则',
  s1: '文本-原始品牌',
  s2: '文本-品牌码',
  s3: '文本-品牌名',
  s4: '文本-长码兜底',
  manual: '人工',
  exclude_reuse: '沿用排除',
  '': '未命中',
}

const statusLabelMap: Record<string, { label: string; color: string }> = {
  url_matched: { label: '精准匹配', color: 'green' },
  matched: { label: '自动匹配', color: 'cyan' },
  confirmed: { label: '人工确认', color: 'blue' },
  excluded: { label: '已排除', color: 'default' },
  ignored: { label: '已忽略', color: 'default' },
  pending: { label: '待匹配', color: 'orange' },
  text_only: { label: 'URL 待确认', color: 'gold' },
  disputed: { label: '争议', color: 'red' },
}

const mappingSourceLabelMap: Record<string, string> = {
  url_import: 'URL 导入',
  match_confirm: '匹配确认沉淀',
  model_db_import: '型号库导入',
  manual: '人工维护',
  '': '未标记来源',
}

const percent = (part: number, total: number) => (total > 0 ? Math.round((part / total) * 1000) / 10 : 0)
const progressPercent = (part: number, total: number) => Math.min(100, percent(part, total))
const unprocessed = (row: ProgressRow) => Math.max(row.dispatched - row.processed, 0)
const notTaskCreated = (row: ProgressRow) => Math.max(row.dispatched - row.task_created, 0)
const taskPercent = (row: ProgressRow) => progressPercent(row.processed, row.task_created)
const overallPercent = (row: ProgressRow) => progressPercent(row.processed, row.dispatched)
const autoMatched = (row: ProgressRow) => row.url_matched + row.auto_matched
const formatMonth = (value: number | null | undefined) => (
  value ? `${Math.floor(value / 100)}-${String(value % 100).padStart(2, '0')}` : '-'
)

const renderStatus = (status: string) => {
  const info = statusLabelMap[status] ?? { label: status, color: 'default' }
  return <Tag color={info.color}>{info.label}</Tag>
}

const progressColumns: ColumnsType<ProgressRow> = [
  {
    title: '月份', dataIndex: 'month', width: 100, fixed: 'left',
    sorter: (a, b) => a.month - b.month, defaultSortOrder: 'descend',
    render: (v: number) => formatMonth(v),
  },
  {
    title: '品类', dataIndex: 'category_name', width: 150, fixed: 'left',
    render: (_: string, row) => row.category_name || row.category_code || '未分类',
  },
  {
    title: '平台', dataIndex: 'platform', width: 110,
    render: (v: string | null) => (v === 'all'
      ? <Tag color="blue">全部平台</Tag>
      : v ? platformLabelMap[v] ?? v : '未区分'),
  },
  {
    title: '分发数据', dataIndex: 'dispatched', width: 110,
    sorter: (a, b) => a.dispatched - b.dispatched,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '已建任务', dataIndex: 'task_created', width: 110,
    sorter: (a, b) => a.task_created - b.task_created,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '未建任务', key: 'not_task_created', width: 110,
    sorter: (a, b) => notTaskCreated(a) - notTaskCreated(b),
    render: (_: unknown, row) => (
      <Text type={notTaskCreated(row) > 0 ? 'warning' : undefined}>{notTaskCreated(row).toLocaleString()}</Text>
    ),
  },
  {
    title: '已清理', dataIndex: 'processed', width: 110,
    sorter: (a, b) => a.processed - b.processed,
    render: (v: number) => <Text type="success">{v.toLocaleString()}</Text>,
  },
  {
    title: '未清理', key: 'unprocessed', width: 100,
    sorter: (a, b) => unprocessed(a) - unprocessed(b),
    render: (_: unknown, row) => unprocessed(row).toLocaleString(),
  },
  {
    title: '任务清洗进度', key: 'task_rate', width: 160,
    sorter: (a, b) => taskPercent(a) - taskPercent(b),
    render: (_: unknown, row) => (row.task_created > 0
      ? <Progress percent={taskPercent(row)} size="small" />
      : <Text type="secondary">未建任务</Text>),
  },
  {
    title: '整体清洗进度', key: 'overall_rate', width: 160,
    sorter: (a, b) => overallPercent(a) - overallPercent(b),
    render: (_: unknown, row) => (row.dispatched > 0
      ? <Progress percent={overallPercent(row)} size="small" />
      : <Text type="secondary">无分发数据</Text>),
  },
  {
    title: '待处理', dataIndex: 'pending', width: 100,
    sorter: (a, b) => a.pending - b.pending,
    render: (v: number) => <Text type={v > 0 ? 'warning' : undefined}>{v.toLocaleString()}</Text>,
  },
  {
    title: '自动匹配', key: 'auto_matched', width: 110,
    sorter: (a, b) => autoMatched(a) - autoMatched(b),
    render: (_: unknown, row) => autoMatched(row).toLocaleString(),
  },
  {
    title: '人工确认', dataIndex: 'confirmed', width: 110,
    sorter: (a, b) => a.confirmed - b.confirmed,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '排除 / 忽略', dataIndex: 'excluded_ignored', width: 110,
    sorter: (a, b) => a.excluded_ignored - b.excluded_ignored,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '已发布', dataIndex: 'published', width: 100,
    sorter: (a, b) => a.published - b.published,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '最后处理时间', dataIndex: 'last_processed_at', width: 170,
    sorter: (a, b) => (a.last_processed_at ?? '').localeCompare(b.last_processed_at ?? ''),
    render: (v: string | null) => v || '-',
  },
  {
    title: '处理完成时间', dataIndex: 'completed_at', width: 170,
    render: (v: string | null) => v
      ? <Tag color="green">{v}</Tag>
      : <Text type="secondary">未完成</Text>,
  },
]

const categoryColumns: ColumnsType<CategoryRow> = [
  { title: '月份', dataIndex: 'month', width: 100, render: (v: string | null) => v || '-' },
  {
    title: '品类', dataIndex: 'category_name', width: 160,
    render: (_: string | null, row) => row.category_name || row.category_code || '-',
  },
  {
    title: '平台', dataIndex: 'platform', width: 90,
    render: (v: string | null) => (v ? platformLabelMap[v] ?? v : '未区分'),
  },
  { title: '任务数', dataIndex: 'tasks', width: 80, sorter: (a, b) => a.tasks - b.tasks },
  {
    title: '匹配条数', dataIndex: 'total', width: 110,
    sorter: (a, b) => a.total - b.total, defaultSortOrder: 'descend',
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '已匹配', dataIndex: 'publishable', width: 110,
    sorter: (a, b) => a.publishable - b.publishable,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: 'URL 匹配', dataIndex: 'url_matched', width: 110,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '待处理', dataIndex: 'actionable', width: 110,
    sorter: (a, b) => a.actionable - b.actionable,
    render: (v: number) => <Text type={v > 0 ? 'warning' : undefined}>{v.toLocaleString()}</Text>,
  },
  {
    title: '匹配率', key: 'rate', width: 160,
    sorter: (a, b) => percent(a.publishable, a.total) - percent(b.publishable, b.total),
    render: (_: unknown, row) => (row.total > 0
      ? <Progress percent={percent(row.publishable, row.total)} size="small" />
      : <Text type="secondary">无数据</Text>),
  },
]

const monthlyColumns: ColumnsType<MonthlyRow> = [
  { title: '月份', dataIndex: 'month', width: 100 },
  { title: '上传文件', dataIndex: 'upload_files', width: 100 },
  { title: '上传行数', dataIndex: 'upload_rows', width: 130, render: (v: number) => v.toLocaleString() },
  { title: '新建清洗任务', dataIndex: 'tasks_created', width: 120 },
  { title: '进入清洗行数', dataIndex: 'rows_in', width: 130, render: (v: number) => v.toLocaleString() },
  { title: '人工处理条数（近似）', dataIndex: 'manual_reviewed', width: 160, render: (v: number) => v.toLocaleString() },
]

const sourceColumns: ColumnsType<SourceRow> = [
  { title: '匹配来源', dataIndex: 'source', width: 160, render: (v: string) => sourceLabelMap[v] ?? v },
  { title: '状态', dataIndex: 'status', width: 120, render: renderStatus },
  { title: '条数', dataIndex: 'count', width: 120, render: (v: number) => v.toLocaleString() },
]

export default function PlatformStatsPage() {
  const navigate = useNavigate()
  const { data, loading, refresh } = useRequest(getPlatformStatsOverview)
  const [liveProgress, setLiveProgress] = useState<PlatformStatsProgress | null>(null)
  const [liveProgressAt, setLiveProgressAt] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string>()
  const [platformFilter, setPlatformFilter] = useState<string>()
  const [monthFilter, setMonthFilter] = useState<string>()
  const [progressCategoryFilter, setProgressCategoryFilter] = useState<string>()
  const [progressPlatformView, setProgressPlatformView] = useState<string>('all')
  const [progressMonthFilter, setProgressMonthFilter] = useState<number>()
  const progress = data?.progress ?? liveProgress
  const progressAt = data?.progress_at ?? liveProgressAt

  const progressTableColumns = useMemo<ColumnsType<ProgressRow>>(() => {
    const openClean = (row: ProgressRow) => {
      const params = new URLSearchParams()
      if (row.category_code) params.set('category_code', row.category_code)
      params.set('month', String(row.month))
      if (row.platform && row.platform !== 'all') params.set('platform', row.platform)
      navigate(`/clean?${params.toString()}`)
    }
    return [
      ...progressColumns,
      {
        title: '操作',
        key: 'action',
        width: 110,
        fixed: 'right',
        render: (_: unknown, row: ProgressRow) => (
          <Button type="link" size="small" onClick={() => openClean(row)}>查看清洗</Button>
        ),
      },
    ]
  }, [navigate])

  // 处理进度由后端后台聚合；缓存未就绪时轮询轻量接口，避免阻塞整页
  useEffect(() => {
    if (!data || progress) return
    let cancelled = false
    const tick = () => {
      getPlatformStatsProgress()
        .then(res => {
          if (!cancelled && res.ready && res.progress) {
            setLiveProgress(res.progress)
            setLiveProgressAt(res.computed_at)
          }
        })
        .catch(() => {})
    }
    tick()
    const timer = window.setInterval(tick, 5000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [data, progress])

  const categoryOptions = useMemo(() => {
    const options = new Map<string, string>()
    for (const row of data?.categories ?? []) {
      const value = row.category_code ?? ''
      if (!options.has(value)) options.set(value, row.category_name || row.category_code || '未分类')
    }
    return Array.from(options, ([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  }, [data?.categories])

  const platformOptions = useMemo(() => {
    const values = new Set((data?.categories ?? []).map(row => row.platform ?? ''))
    return Array.from(values, value => ({
      value,
      label: value ? platformLabelMap[value] ?? value : '未区分',
    }))
  }, [data?.categories])

  const monthOptions = useMemo(() => {
    const values = new Set((data?.categories ?? []).map(row => row.month ?? ''))
    return Array.from(values, value => ({ value, label: value || '未知' }))
      .sort((a, b) => b.value.localeCompare(a.value))
  }, [data?.categories])

  const progressCategoryOptions = useMemo(() => {
    const options = new Map<string, string>()
    for (const row of progress?.categories ?? []) {
      const value = row.category_code ?? ''
      if (!options.has(value)) options.set(value, row.category_name || row.category_code || '未分类')
    }
    return Array.from(options, ([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  }, [progress?.categories])

  const progressPlatformOptions = useMemo(() => {
    const values = new Set((progress?.categories ?? []).map(row => row.platform ?? ''))
    return Array.from(values, value => ({
      value,
      label: value ? platformLabelMap[value] ?? value : '未区分',
    }))
  }, [progress?.categories])

  const progressMonthOptions = useMemo(
    () => (progress?.months ?? []).map(item => ({
      value: item.month,
      label: formatMonth(item.month),
    })),
    [progress?.months],
  )

  const filteredCategories = useMemo(
    () => (data?.categories ?? []).filter(row => (
      (categoryFilter === undefined || (row.category_code ?? '') === categoryFilter)
      && (platformFilter === undefined || (row.platform ?? '') === platformFilter)
      && (monthFilter === undefined || (row.month ?? '') === monthFilter)
    )),
    [data?.categories, categoryFilter, platformFilter, monthFilter],
  )

  const filteredProgress = useMemo(() => {
    const rows = (progress?.categories ?? []).filter(row => (
      (progressMonthFilter === undefined || row.month === progressMonthFilter)
      && (progressCategoryFilter === undefined || (row.category_code ?? '') === progressCategoryFilter)
    ))
    if (progressPlatformView !== 'all') {
      return rows.filter(row => (row.platform ?? '') === progressPlatformView)
    }
    const grouped = new Map<string, ProgressRow>()
    for (const row of rows) {
      const key = `${row.month}-${row.category_code ?? ''}`
      const existing = grouped.get(key)
      if (!existing) {
        grouped.set(key, { ...row, platform: 'all' })
        continue
      }
      existing.dispatched += row.dispatched
      existing.task_created += row.task_created
      existing.processed += row.processed
      existing.matched += row.matched
      existing.url_matched += row.url_matched
      existing.auto_matched += row.auto_matched
      existing.confirmed += row.confirmed
      existing.excluded_ignored += row.excluded_ignored
      existing.pending += row.pending
      existing.published += row.published
      if (row.last_processed_at && (!existing.last_processed_at || row.last_processed_at > existing.last_processed_at)) {
        existing.last_processed_at = row.last_processed_at
      }
    }
    return Array.from(grouped.values())
  }, [
    progress?.categories,
    progressMonthFilter,
    progressCategoryFilter,
    progressPlatformView,
  ])

  const progressTotals = useMemo(() => filteredProgress.reduce(
    (acc, row) => ({
      dispatched: acc.dispatched + row.dispatched,
      task_created: acc.task_created + row.task_created,
      processed: acc.processed + row.processed,
    }),
    { dispatched: 0, task_created: 0, processed: 0 },
  ), [filteredProgress])

  if (!data) {
    return <Card loading={loading} />
  }

  const { upload, clean, match, assets } = data
  const automatedRate = percent(match.auto_matched, match.total)
  const publishableRate = percent(match.publishable, match.total)
  const finishedRate = percent(clean.clean_finished, clean.task_total)
  const overview = progress
    ? (progressMonthFilter === undefined
      ? progress
      : (progress.months ?? []).find(item => item.month === progressMonthFilter)
        ?? {
          uploaded_rows: null,
          dispatchable: 0,
          task_created: 0,
          not_task_created: 0,
          processed: 0,
          not_processed: 0,
          matched: 0,
          url_matched: 0,
          auto_matched: 0,
          confirmed: 0,
          excluded_ignored: 0,
          pending: 0,
          task_no_result: 0,
          published: 0,
        })
    : null
  const completionRate = overview ? progressPercent(overview.processed, overview.dispatchable) : 0

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="口径说明"
        description="总览与明细均按「分发条目」统计（同一商品分发到多个品类会分别计数）：值得分发 = 最新一次已完成分发批次中命中规则的条目；已清理 = 已有处理结论的条目，其中自动匹配 = URL 精准匹配 + 自动匹配，人工确认 = 人工选定型号，二者分开计数。对账关系：值得分发 = 已建任务 + 未建任务 = 已清理 + 未清理；已建任务 = 已清理 + 当前待处理 + 已建任务未出结果；已清理 = 自动匹配 + 人工确认 + 已排除/忽略。已发布为任务级发布行数，不与条目相加。明细可切换平台聚合或拆分；最后处理时间取分组内最近一次匹配更新时间。时间按北京时间统计；处理进度后台定时刷新，最多延迟约 5 分钟。"
        action={
          <Space direction="vertical" align="end">
            <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>刷新</Button>
            <Text type="secondary">统计时间：{data.generated_at}</Text>
            <Text type="secondary">处理进度统计时间：{progressAt ?? '统计中，稍后自动刷新'}</Text>
            <Text type="secondary">入库行数 / 历史对照每小时刷新：{data.slow_counts_at ?? '统计中，稍后刷新'}</Text>
          </Space>
        }
      />

      {progress && overview ? (
        <>
      <Card
        title={progressMonthFilter === undefined ? '处理进度总览' : `处理进度总览（${formatMonth(progressMonthFilter)}）`}
        extra={(
          <Select
            allowClear
            style={{ width: 160 }}
            placeholder="全部月份"
            value={progressMonthFilter}
            options={progressMonthOptions}
            onChange={setProgressMonthFilter}
          />
        )}
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="上传入库数据总量" value={overview.uploaded_rows ?? '统计中…'} suffix={overview.uploaded_rows == null ? undefined : '条'} />
            {progressMonthFilter === undefined && (
              <Text type="secondary">上传文件行数 {upload.file_rows.toLocaleString()}，去重拦截 {upload.dedup_skipped_rows.toLocaleString()}</Text>
            )}
          </Col>
          <Col span={6}>
            <Statistic title="值得分发（分发条目）" value={overview.dispatchable} suffix="条" />
          </Col>
          <Col span={6}>
            <Statistic title="已清理" value={overview.processed} suffix="条" valueStyle={{ color: '#3f8600' }} />
          </Col>
          <Col span={6}>
            <Statistic
              title="清理占比"
              value={completionRate}
              suffix="%"
              valueStyle={{ color: completionRate >= 100 ? '#3f8600' : '#1677ff' }}
            />
          </Col>
        </Row>
        <Progress
          style={{ marginTop: 20 }}
          percent={completionRate}
          format={() => `${overview.processed.toLocaleString()} / ${overview.dispatchable.toLocaleString()}`}
        />
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={6}><Statistic title="已建任务" value={overview.task_created} /></Col>
          <Col span={6}><Statistic title="未建任务" value={overview.not_task_created} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}>
            <Statistic title="自动匹配" value={overview.url_matched + overview.auto_matched} valueStyle={{ color: '#3f8600' }} />
            <Text type="secondary">
              URL 精准 {overview.url_matched.toLocaleString()} + 自动 {overview.auto_matched.toLocaleString()}
            </Text>
          </Col>
          <Col span={6}>
            <Statistic title="人工确认" value={overview.confirmed} />
            <Text type="secondary">人工选定型号，单独计数</Text>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={6}><Statistic title="已排除 / 忽略" value={overview.excluded_ignored} /></Col>
          <Col span={6}><Statistic title="当前待处理" value={overview.pending} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}><Statistic title="已建任务未出结果" value={overview.task_no_result} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}><Statistic title="未清理" value={overview.not_processed} valueStyle={{ color: '#d48806' }} /></Col>
        </Row>
        <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          对账关系：值得分发 = 已建任务 + 未建任务 = 已清理 + 未清理；已建任务 = 已清理 + 当前待处理 + 已建任务未出结果；已清理 = 自动匹配 + 人工确认 + 已排除 / 忽略。
        </Text>
        <Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
          已发布到分析库：{overview.published.toLocaleString()} 行（任务级发布行数，不参与上方条目对账）。
        </Text>
      </Card>

      <Card title="处理进度明细（月份 / 品类 / 平台）">
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            style={{ width: 150 }}
            placeholder="全部月份"
            value={progressMonthFilter}
            options={progressMonthOptions}
            onChange={setProgressMonthFilter}
          />
          <Select
            allowClear
            showSearch
            style={{ width: 180 }}
            placeholder="品类"
            optionFilterProp="label"
            value={progressCategoryFilter}
            options={progressCategoryOptions}
            onChange={setProgressCategoryFilter}
          />
          <Select
            style={{ width: 170 }}
            value={progressPlatformView}
            options={[{ value: 'all', label: '全部平台（聚合）' }, ...progressPlatformOptions]}
            onChange={setProgressPlatformView}
          />
        </Space>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}><Statistic title="分发合计" value={progressTotals.dispatched} /></Col>
          <Col span={4}><Statistic title="已建任务" value={progressTotals.task_created} /></Col>
          <Col span={4}>
            <Statistic
              title="未建任务"
              value={Math.max(progressTotals.dispatched - progressTotals.task_created, 0)}
              valueStyle={{ color: '#d48806' }}
            />
          </Col>
          <Col span={4}><Statistic title="已清理" value={progressTotals.processed} valueStyle={{ color: '#3f8600' }} /></Col>
          <Col span={4}>
            <Statistic
              title="未清理"
              value={Math.max(progressTotals.dispatched - progressTotals.processed, 0)}
              valueStyle={{ color: '#d48806' }}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="整体清洗进度"
              value={progressPercent(progressTotals.processed, progressTotals.dispatched)}
              suffix="%"
            />
          </Col>
        </Row>
        <Table
          dataSource={filteredProgress}
          columns={progressTableColumns}
          rowKey={row => `${row.month}-${row.category_code ?? ''}-${row.platform ?? ''}`}
          size="small"
          scroll={{ x: 2050 }}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>
        </>
      ) : (
        <>
          <Card title="处理进度总览" loading />
          <Card title="处理进度明细（月份 / 品类 / 平台）" loading />
        </>
      )}

      <Collapse
        items={[
          {
            key: 'upload-clean-match',
            label: '上传 / 清洗 / 匹配详情',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card title="数据上传" size="small">
                  <Row gutter={16}>
                    <Col span={6}><Statistic title="上传文件数" value={upload.file_count} /></Col>
                    <Col span={6}><Statistic title="上传数据行数" value={upload.file_rows} /></Col>
                    <Col span={6}><Statistic title="实际入库行数" value={upload.raw_rows ?? '统计中…'} valueStyle={{ color: '#3f8600' }} /></Col>
                    <Col span={6}><Statistic title="去重拦截行数" value={upload.dedup_skipped_rows} /></Col>
                  </Row>
                  <Text type="secondary">
                    首次上传：{upload.first_uploaded_at ?? '-'}　最近上传：{upload.last_uploaded_at ?? '-'}
                  </Text>
                </Card>

                <Card title="清洗任务" size="small">
                  <Row gutter={16}>
                    <Col span={4}><Statistic title="有效任务" value={clean.task_total} /></Col>
                    <Col span={4}>
                      <Statistic title="清洗完成" value={clean.clean_finished} valueStyle={{ color: '#3f8600' }} suffix={<Text type="secondary" style={{ fontSize: 14 }}>{finishedRate}%</Text>} />
                    </Col>
                    <Col span={4}><Statistic title="仍有待处理" value={clean.has_pending} valueStyle={{ color: '#d48806' }} /></Col>
                    <Col span={4}><Statistic title="处理中 / 失败" value={`${clean.processing} / ${clean.failed}`} /></Col>
                    <Col span={4}><Statistic title="已发布任务" value={clean.published_tasks} /></Col>
                    <Col span={4}><Statistic title="发布到分析库行数" value={clean.published_rows} /></Col>
                  </Row>
                  <Row gutter={16} style={{ marginTop: 16 }}>
                    <Col span={6}><Statistic title="进入清洗行数" value={clean.row_in} /></Col>
                    <Col span={6}><Statistic title="清洗后行数" value={clean.row_out} /></Col>
                    <Col span={6}><Statistic title="过滤行数" value={clean.row_filtered} /></Col>
                    <Col span={6}><Statistic title="已删除任务" value={clean.archived} valueStyle={{ color: '#8c8c8c' }} /></Col>
                  </Row>
                </Card>

                <Card title="匹配数据" size="small">
                  <Row gutter={16}>
                    <Col span={6}><Statistic title="匹配条数" value={match.total} /></Col>
                    <Col span={6}>
                      <Statistic title="已匹配" value={match.publishable} valueStyle={{ color: '#3f8600' }} suffix={<Text type="secondary" style={{ fontSize: 14 }}>{publishableRate}%</Text>} />
                    </Col>
                    <Col span={6}><Statistic title="已匹配（商品去重）" value={match.publishable_distinct} /></Col>
                    <Col span={6}><Statistic title="系统自动匹配率" value={automatedRate} suffix="%" /></Col>
                  </Row>
                  <Row gutter={16} style={{ marginTop: 16 }}>
                    <Col span={4}><Statistic title="URL 精准匹配" value={match.url_matched} /></Col>
                    <Col span={4}><Statistic title="自动匹配" value={match.matched} /></Col>
                    <Col span={4}><Statistic title="人工确认" value={match.confirmed} /></Col>
                    <Col span={4}><Statistic title="排除 / 忽略" value={match.excluded + match.ignored} /></Col>
                    <Col span={4}><Statistic title="待匹配" value={match.pending} valueStyle={{ color: '#d48806' }} /></Col>
                    <Col span={4}><Statistic title="URL 待确认 / 争议" value={`${match.text_only.toLocaleString()} / ${match.disputed.toLocaleString()}`} valueStyle={{ color: '#d48806' }} /></Col>
                  </Row>
                  <Progress
                    style={{ marginTop: 16 }}
                    percent={publishableRate}
                    success={{ percent: percent(match.url_matched, match.total) }}
                    format={() => `${publishableRate}%`}
                  />
                  <Text type="secondary">深绿：URL 精准匹配占比；浅色：已匹配总占比</Text>
                </Card>
              </Space>
            ),
          },
          {
            key: 'category-monthly',
            label: '品类 / 平台明细（按月）',
            children: (
              <>
                <Space wrap style={{ marginBottom: 16 }}>
                  <Select
                    allowClear
                    showSearch
                    style={{ width: 180 }}
                    placeholder="品类"
                    optionFilterProp="label"
                    value={categoryFilter}
                    options={categoryOptions}
                    onChange={setCategoryFilter}
                  />
                  <Select
                    allowClear
                    style={{ width: 140 }}
                    placeholder="平台"
                    value={platformFilter}
                    options={platformOptions}
                    onChange={setPlatformFilter}
                  />
                  <Select
                    allowClear
                    style={{ width: 140 }}
                    placeholder="月份"
                    value={monthFilter}
                    options={monthOptions}
                    onChange={setMonthFilter}
                  />
                </Space>
                <Table
                  dataSource={filteredCategories}
                  columns={categoryColumns}
                  rowKey={row => `${row.month ?? ''}-${row.category_code ?? ''}-${row.platform ?? ''}`}
                  size="small"
                  scroll={{ x: 1000 }}
                  pagination={{ pageSize: 20 }}
                />
              </>
            ),
          },
          {
            key: 'trend-source',
            label: '按月趋势与匹配来源',
            children: (
              <Row gutter={16}>
                <Col span={14}>
                  <Card title="按月趋势" size="small">
                    <Table dataSource={data.monthly} columns={monthlyColumns} rowKey="month" size="small" pagination={false} scroll={{ x: 740 }} />
                  </Card>
                </Col>
                <Col span={10}>
                  <Card title="匹配来源分布" size="small">
                    <Table
                      dataSource={data.sources}
                      columns={sourceColumns}
                      rowKey={row => `${row.source}-${row.status}`}
                      size="small"
                      pagination={{ pageSize: 10 }}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'assets',
            label: '沉淀资产',
            children: (
              <Card size="small">
                <Row gutter={16}>
                  <Col span={4}><Statistic title="URL 映射" value={assets.url_mappings} /></Col>
                  <Col span={4}><Statistic title="已关联型号的映射" value={assets.url_mappings_with_model} /></Col>
                  <Col span={4}><Statistic title="历史对照" value={assets.historical_mappings ?? '统计中…'} /></Col>
                  <Col span={4}><Statistic title="型号 / 品牌" value={`${assets.models.toLocaleString()} / ${assets.brands.toLocaleString()}`} /></Col>
                  <Col span={4}><Statistic title="排除库" value={assets.exclusions} /></Col>
                  <Col span={4}><Statistic title="用户（启用 / 近30天登录）" value={`${assets.active_users} / ${assets.login_users_30d}`} /></Col>
                </Row>
                <Space wrap style={{ marginTop: 16 }}>
                  {assets.url_mapping_sources.map(item => (
                    <Tag key={item.source}>
                      {mappingSourceLabelMap[item.source] ?? item.source}：{item.count.toLocaleString()}（有型号 {item.with_model.toLocaleString()}）
                    </Tag>
                  ))}
                </Space>
              </Card>
            ),
          },
        ]}
      />
    </Space>
  )
}
