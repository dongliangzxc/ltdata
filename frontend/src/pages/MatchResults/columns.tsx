import { Tag, Tooltip, Typography, Button, InputNumber, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReviewedMatchResultOut, PriceFlag } from '../../services/api'

const { Text } = Typography

export type BuildMatchResultsColumnsOptions = {
  coefficientDrafts?: Record<number, number | null>
  editedCoefficientIds?: Set<number>
  savingCoefficientIds?: Set<number>
  onCoefficientChange?: (matchId: number, value: number | null) => void
  onSaveCoefficient?: (matchId: number) => void
  onReselect: (row: ReviewedMatchResultOut) => void
}

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
    's0.5': { label: '规则命中', color: 'green' },
    s1: { label: '名称规则命中', color: 'green' },
    s2: { label: '人工确认', color: 'blue' },
    manual: { label: '人工确认', color: 'blue' },
  }
  return source ? map[source] : undefined
}

const renderMatchSource = (source?: string | null) => {
  const entry = matchSourceMeta(source)
  if (!source) return <Tag color="default">未知</Tag>
  return entry ? <Tag color={entry.color}>{entry.label}</Tag> : <Tag>{source}</Tag>
}

const MATCH_STATUS_META: Record<string, { label: string; color: string }> = {
  matched: { label: '已匹配', color: 'green' },
  url_matched: { label: '精准匹配', color: 'cyan' },
  confirmed: { label: '已人工确认', color: 'blue' },
  excluded: { label: '已排除', color: 'default' },
}

const renderMatchStatus = (value: string) => {
  const meta = MATCH_STATUS_META[value] ?? { label: value, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

const hasDisplayModel = (brand?: string | null, model?: string | null) =>
  Boolean(model && brand && brand !== '未识别品牌')

const getEffectiveSalesQty = (row: ReviewedMatchResultOut) => row.corrected_sales_qty ?? row.sales_qty ?? null

const getAdjustedSalesQty = (row: ReviewedMatchResultOut, options: BuildMatchResultsColumnsOptions) => {
  const hasLocalEdit = options.editedCoefficientIds?.has(row.id) ?? false
  if (!hasLocalEdit && row.adjusted_sales_qty != null) return row.adjusted_sales_qty
  const base = getEffectiveSalesQty(row)
  const coefficient = hasLocalEdit
    ? options.coefficientDrafts?.[row.id] ?? null
    : row.sales_coefficient ?? null
  return base != null && coefficient != null ? Math.round(base * coefficient) : base
}

const renderNumber = (value?: number | null) => value != null ? value.toLocaleString() : '-'

export function buildMatchResultsColumns(
  optionsOrReselect: BuildMatchResultsColumnsOptions | ((row: ReviewedMatchResultOut) => void),
): ColumnsType<ReviewedMatchResultOut> {
  const options: BuildMatchResultsColumnsOptions = typeof optionsOrReselect === 'function'
    ? { onReselect: optionsOrReselect }
    : optionsOrReselect

  return [
    {
      title: '商品名称', dataIndex: 'item_name', ellipsis: true,
      render: (value: string | null) =>
        value ? <Tooltip title={value}><Text style={{ fontSize: 12 }}>{value}</Text></Tooltip> : '-',
    },
    { title: '品牌', dataIndex: 'brand_raw', width: 110, render: (value: string | null) => value ?? '-' },
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
        const flag = row.price_flag
        if (!flag) return <Tag>无历史</Tag>
        const meta = priceFlagMeta[flag]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '参考均价', dataIndex: 'price_ref', width: 100,
      render: (value: number | null) => value != null ? value.toFixed(2) : '-',
    },
    {
      title: '原销量', dataIndex: 'sales_qty', width: 90,
      render: (value: number | null) => renderNumber(value),
    },
    {
      title: '修正销量', width: 100,
      render: (_: unknown, row: ReviewedMatchResultOut) => renderNumber(getEffectiveSalesQty(row)),
    },
    {
      title: '调整系数', width: 190,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const value = options.coefficientDrafts?.[row.id] ?? row.sales_coefficient ?? null
        if (!options.onCoefficientChange || !options.onSaveCoefficient) {
          return value != null ? value : <Text type="secondary">不调整</Text>
        }
        const edited = options.editedCoefficientIds?.has(row.id) ?? false
        const saving = options.savingCoefficientIds?.has(row.id) ?? false
        return (
          <Space size={6}>
            <InputNumber
              size="small"
              min={0}
              step={0.01}
              precision={2}
              placeholder="不调整"
              value={value}
              onChange={(next) => options.onCoefficientChange?.(row.id, next == null ? null : Number(next))}
              style={{ width: 92 }}
            />
            <Button
              size="small"
              disabled={!edited}
              loading={saving}
              onClick={() => options.onSaveCoefficient?.(row.id)}
            >
              保存
            </Button>
          </Space>
        )
      },
    },
    {
      title: '调整后销量', width: 110,
      render: (_: unknown, row: ReviewedMatchResultOut) => renderNumber(getAdjustedSalesQty(row, options)),
    },
    {
      title: '状态', dataIndex: 'match_status', width: 110,
      render: (value: string) => renderMatchStatus(value),
    },
    {
      title: '来源', width: 130,
      render: (_: unknown, row: ReviewedMatchResultOut) => renderMatchSource(row.match_source),
    },
    {
      title: '操作', width: 100, fixed: 'right',
      render: (_: unknown, row: ReviewedMatchResultOut) =>
        <Button type="link" size="small" onClick={() => options.onReselect(row)}>重新选择</Button>,
    },
  ]
}
