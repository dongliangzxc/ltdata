import { Alert, Button, Card, Col, Progress, Row, Space, Statistic, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { getPlatformStatsOverview, type PlatformStatsOverview } from '../../services/api'

const { Text } = Typography

type CategoryRow = PlatformStatsOverview['categories'][number]
type MonthlyRow = PlatformStatsOverview['monthly'][number]
type SourceRow = PlatformStatsOverview['sources'][number]

const platformLabelMap: Record<string, string> = {
  jd: '京东',
  tmall: '天猫',
  taobao: '淘宝',
  douyin: '抖音',
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

const renderStatus = (status: string) => {
  const info = statusLabelMap[status] ?? { label: status, color: 'default' }
  return <Tag color={info.color}>{info.label}</Tag>
}

const categoryColumns: ColumnsType<CategoryRow> = [
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

  if (!data) {
    return <Card loading={loading} />
  }

  const { upload, clean, match, assets } = data
  const automatedRate = percent(match.auto_matched, match.total)
  const publishableRate = percent(match.publishable, match.total)
  const finishedRate = percent(clean.clean_finished, clean.task_total)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="口径说明"
        description="清洗任务与匹配数据均不含已删除任务和干扰过滤行；匹配条数按任务计（同一商品分发到多个任务会重复计数），去重数单独列出。已匹配 = 精准匹配 + 自动匹配 + 人工确认。时间按北京时间统计。"
        action={
          <Space direction="vertical" align="end">
            <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>刷新</Button>
            <Text type="secondary">统计时间：{data.generated_at}</Text>
          </Space>
        }
      />

      <Card title="数据上传">
        <Row gutter={16}>
          <Col span={6}><Statistic title="上传文件数" value={upload.file_count} /></Col>
          <Col span={6}><Statistic title="上传数据行数" value={upload.file_rows} /></Col>
          <Col span={6}><Statistic title="实际入库行数" value={upload.raw_rows} valueStyle={{ color: '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="去重拦截行数" value={upload.dedup_skipped_rows} /></Col>
        </Row>
        <Text type="secondary">
          首次上传：{upload.first_uploaded_at ?? '-'}　最近上传：{upload.last_uploaded_at ?? '-'}
        </Text>
      </Card>

      <Card title="清洗任务">
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

      <Card title="匹配数据">
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

      <Card title="品类 / 平台明细">
        <Table
          dataSource={data.categories}
          columns={categoryColumns}
          rowKey={row => `${row.category_code ?? ''}-${row.platform ?? ''}`}
          size="small"
          scroll={{ x: 900 }}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Row gutter={16}>
        <Col span={14}>
          <Card title="按月趋势">
            <Table dataSource={data.monthly} columns={monthlyColumns} rowKey="month" size="small" pagination={false} scroll={{ x: 740 }} />
          </Card>
        </Col>
        <Col span={10}>
          <Card title="匹配来源分布">
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

      <Card title="沉淀资产">
        <Row gutter={16}>
          <Col span={4}><Statistic title="URL 映射" value={assets.url_mappings} /></Col>
          <Col span={4}><Statistic title="已关联型号的映射" value={assets.url_mappings_with_model} /></Col>
          <Col span={4}><Statistic title="历史对照" value={assets.historical_mappings} /></Col>
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
    </Space>
  )
}
