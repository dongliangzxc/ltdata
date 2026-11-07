import { useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Collapse, Progress, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { getPlatformStatsOverview, type PlatformStatsOverview } from '../../services/api'

const { Text } = Typography

type CategoryRow = PlatformStatsOverview['categories'][number]
type MonthlyRow = PlatformStatsOverview['monthly'][number]
type SourceRow = PlatformStatsOverview['sources'][number]
type ProgressRow = PlatformStatsOverview['progress']['categories'][number]

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
    title: '品类', dataIndex: 'category_name', width: 160, fixed: 'left',
    render: (_: string, row) => row.category_name || row.category_code || '未分类',
  },
  {
    title: '平台', dataIndex: 'platform', width: 100,
    render: (v: string | null) => (v ? platformLabelMap[v] ?? v : '未区分'),
  },
  {
    title: '分发数据', dataIndex: 'dispatched', width: 120,
    sorter: (a, b) => a.dispatched - b.dispatched,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '已清理', dataIndex: 'processed', width: 120,
    sorter: (a, b) => a.processed - b.processed,
    render: (v: number) => <Text type="success">{v.toLocaleString()}</Text>,
  },
  {
    title: '待处理', dataIndex: 'pending', width: 110,
    sorter: (a, b) => a.pending - b.pending,
    render: (v: number) => <Text type={v > 0 ? 'warning' : undefined}>{v.toLocaleString()}</Text>,
  },
  {
    title: '未清理', key: 'unprocessed', width: 110,
    sorter: (a, b) => unprocessed(a) - unprocessed(b),
    render: (_: unknown, row) => unprocessed(row).toLocaleString(),
  },
  {
    title: '已匹配成功', dataIndex: 'matched', width: 120,
    sorter: (a, b) => a.matched - b.matched,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '已发布', dataIndex: 'published', width: 110,
    sorter: (a, b) => a.published - b.published,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '清理占比', key: 'rate', width: 170,
    sorter: (a, b) => progressPercent(a.processed, a.dispatched) - progressPercent(b.processed, b.dispatched),
    render: (_: unknown, row) => (row.dispatched > 0
      ? <Progress percent={progressPercent(row.processed, row.dispatched)} size="small" />
      : <Text type="secondary">无分发数据</Text>),
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
  const { data, loading, refresh } = useRequest(getPlatformStatsOverview)
  const [categoryFilter, setCategoryFilter] = useState<string>()
  const [platformFilter, setPlatformFilter] = useState<string>()
  const [monthFilter, setMonthFilter] = useState<string>()
  const [progressCategoryFilter, setProgressCategoryFilter] = useState<string>()
  const [progressPlatformFilter, setProgressPlatformFilter] = useState<string>()
  const [progressMonthFilter, setProgressMonthFilter] = useState<number>()

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
    for (const row of data?.progress.categories ?? []) {
      const value = row.category_code ?? ''
      if (!options.has(value)) options.set(value, row.category_name || row.category_code || '未分类')
    }
    return Array.from(options, ([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  }, [data?.progress.categories])

  const progressPlatformOptions = useMemo(() => {
    const values = new Set((data?.progress.categories ?? []).map(row => row.platform ?? ''))
    return Array.from(values, value => ({
      value,
      label: value ? platformLabelMap[value] ?? value : '未区分',
    }))
  }, [data?.progress.categories])

  const progressMonthOptions = useMemo(
    () => (data?.progress.months ?? []).map(item => ({
      value: item.month,
      label: formatMonth(item.month),
    })),
    [data?.progress.months],
  )

  const filteredCategories = useMemo(
    () => (data?.categories ?? []).filter(row => (
      (categoryFilter === undefined || (row.category_code ?? '') === categoryFilter)
      && (platformFilter === undefined || (row.platform ?? '') === platformFilter)
      && (monthFilter === undefined || (row.month ?? '') === monthFilter)
    )),
    [data?.categories, categoryFilter, platformFilter, monthFilter],
  )

  const filteredProgress = useMemo(
    () => (data?.progress.categories ?? []).filter(row => (
      (progressMonthFilter === undefined || row.month === progressMonthFilter)
      && (progressCategoryFilter === undefined || (row.category_code ?? '') === progressCategoryFilter)
      && (progressPlatformFilter === undefined || (row.platform ?? '') === progressPlatformFilter)
    )),
    [data?.progress.categories, progressMonthFilter, progressCategoryFilter, progressPlatformFilter],
  )

  if (!data) {
    return <Card loading={loading} />
  }

  const { upload, clean, match, assets, progress } = data
  const automatedRate = percent(match.auto_matched, match.total)
  const publishableRate = percent(match.publishable, match.total)
  const finishedRate = percent(clean.clean_finished, clean.task_total)
  const overview = progressMonthFilter === undefined
    ? progress
    : progress.months.find(item => item.month === progressMonthFilter)
      ?? { uploaded_rows: null, dispatchable: 0, processed: 0, matched: 0, pending: 0, published: 0 }
  const completionRate = progressPercent(overview.processed, overview.dispatchable)
  const remaining = Math.max(overview.dispatchable - overview.processed, 0)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="口径说明"
        description="总览按「上传 → 值得分发 → 已清理」统计，三者均按商品去重：值得分发取每个文件/上传批次最新一次已完成分发的商品；已清理为其中已有处理结论（精准匹配、自动匹配、人工确认、已排除、已忽略）的商品数。月份取原始数据月份，可按月份筛选。下方明细按「月份 × 品类 × 平台」统计条目数，同一商品分发到多个品类会分别计数。清洗任务与匹配数据均不含已删除任务和干扰过滤行；时间按北京时间统计；处理进度为近 2 分钟内的聚合结果。"
        action={
          <Space direction="vertical" align="end">
            <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>刷新</Button>
            <Text type="secondary">统计时间：{data.generated_at}</Text>
            <Text type="secondary">入库行数 / 历史对照每小时刷新：{data.slow_counts_at ?? '统计中，稍后刷新'}</Text>
          </Space>
        }
      />

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
            <Statistic title="值得分发" value={overview.dispatchable} suffix="条" />
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
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={6}><Statistic title="已匹配成功" value={overview.matched} valueStyle={{ color: '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="已发布到分析库" value={overview.published} /></Col>
          <Col span={6}><Statistic title="当前待处理" value={overview.pending} valueStyle={{ color: '#d48806' }} /></Col>
          <Col span={6}><Statistic title="未清理" value={remaining} valueStyle={{ color: remaining > 0 ? '#d48806' : '#8c8c8c' }} /></Col>
        </Row>
      </Card>

      <Card title="处理进度明细（月份 / 品类 / 平台）">
        <Space wrap style={{ marginBottom: 16 }}>
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
            allowClear
            style={{ width: 140 }}
            placeholder="平台"
            value={progressPlatformFilter}
            options={progressPlatformOptions}
            onChange={setProgressPlatformFilter}
          />
        </Space>
        <Table
          dataSource={filteredProgress}
          columns={progressColumns}
          rowKey={row => `${row.month}-${row.category_code ?? ''}-${row.platform ?? ''}`}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

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
