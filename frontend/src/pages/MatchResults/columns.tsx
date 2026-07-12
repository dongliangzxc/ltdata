import { Tag, Tooltip, Typography, Button } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReviewedMatchResultOut, PriceFlag } from '../../services/api'

const { Text } = Typography

const priceFlagMeta: Record<PriceFlag, { label: string; color: string }> = {
  ok: { label: '正常', color: 'green' },
  high: { label: '偏高', color: 'red' },
  low: { label: '偏低', color: 'orange' },
  no_history: { label: '无历史', color: 'default' },
}

const matchSourceMeta = (source?: string | null) => {
  const map: Record<string, { label: string; color: string }> = {
    s0: { label: 'URL映射命中', color: 'blue' },
    historical: { label: '历史库命中', color: 'purple' },
    's0.5': { label: '规则命中', color: 'cyan' },
    s1: { label: '品牌字段匹配', color: 'green' },
    s2: { label: '标题品牌码匹配', color: 'green' },
    s3: { label: '标题品牌名匹配', color: 'green' },
    s4: { label: '型号码兜底匹配', color: 'orange' },
    manual: { label: '人工确认', color: 'blue' },
  }
  return source ? map[source] : undefined
}
const renderMatchSource = (source?: string | null) => {
  const entry = matchSourceMeta(source)
  if (!source) return <Tag color="default">未知</Tag>
  return entry ? <Tag color={entry.color}>{entry.label}</Tag> : <Tag>{source}</Tag>
}

const isPlaceholderCode = (v?: string | null) => {
  const s = (v ?? '').trim()
  return s === '' || /^-+$/.test(s)
}
const hasDisplayModel = (b?: string | null, m?: string | null) =>
  !isPlaceholderCode(b) && !isPlaceholderCode(m)

const formatNumber = (v?: number | null) => v != null ? v.toLocaleString() : '-'

const statusColor = (v: string) => {
  if (v === 'confirmed') return 'blue'
  if (v === 'url_matched') return 'green'
  return 'green'
}

export function buildMatchResultsColumns(
  onReselect: (row: ReviewedMatchResultOut) => void,
): ColumnsType<ReviewedMatchResultOut> {
  return [
    {
      title: '商品名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string | null) =>
        v ? <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip> : '-',
    },
    { title: '品牌', dataIndex: 'brand_raw', width: 110, render: (v: string | null) => v ?? '-' },
    {
      title: '匹配型号', width: 180,
      render: (_: unknown, row: ReviewedMatchResultOut) =>
        hasDisplayModel(row.brand_code, row.model_code)
          ? <Text code style={{ fontSize: 12 }}>[{row.brand_code}] {row.model_code}</Text>
          : <Text type="secondary">-</Text>,
    },
    {
      title: '价格预警', width: 100,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const f = row.price_flag
        if (!f) return <Tag color="default">-</Tag>
        const m = priceFlagMeta[f]
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    {
      title: '参考均价', dataIndex: 'price_ref', width: 100,
      render: (v: number | null) => v != null ? `¥${v.toLocaleString()}` : '-',
    },
    {
      title: '原销量', dataIndex: 'sales_qty', width: 90,
      render: (v: number | null) => formatNumber(v),
    },
    {
      title: '状态', dataIndex: 'match_status', width: 100,
      render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
    },
    {
      title: '来源', width: 130,
      render: (_: unknown, row: ReviewedMatchResultOut) => renderMatchSource(row.match_source),
    },
    {
      title: '任务', dataIndex: 'clean_job_id', width: 80,
      render: (v: number) => <Text type="secondary">#{v}</Text>,
    },
    {
      title: '操作', width: 100, fixed: 'right' as const,
      render: (_: unknown, row: ReviewedMatchResultOut) => (
        <Button size="small" type="link" onClick={() => onReselect(row)}>重新选择</Button>
      ),
    },
  ]
}
