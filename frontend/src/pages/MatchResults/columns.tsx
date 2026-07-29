import { Tag, Tooltip, Typography, Button, InputNumber, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReviewedMatchResultOut, PriceFlag } from '../../services/api'

const { Text, Link } = Typography

export type BuildMatchResultsColumnsOptions = {
  coefficientDrafts?: Record<number, number | null>
  editedCoefficientIds?: Set<number>
  savingCoefficientIds?: Set<number>
  priceCoefficientDrafts?: Record<number, number | null>
  editedPriceIds?: Set<number>
  savingPriceIds?: Set<number>
  onCoefficientChange?: (matchId: number, value: number | null) => void
  onSaveCoefficient?: (matchId: number) => void
  onPriceCoefficientChange?: (matchId: number, value: number | null) => void
  onSavePrice?: (matchId: number) => void
  onReselect: (row: ReviewedMatchResultOut) => void
}

const priceFlagMeta: Record<PriceFlag, { label: string; color: string }> = {
  ok: { label: '正常', color: 'green' },
  high: { label: '偏高', color: 'red' },
  low: { label: '偏低', color: 'orange' },
  no_history: { label: '无历史', color: 'default' },
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

const getOriginalPrice = (row: ReviewedMatchResultOut) => row.price ?? null

const getPriceCoefficient = (row: ReviewedMatchResultOut, options: BuildMatchResultsColumnsOptions) => {
  if (options.editedPriceIds?.has(row.id)) return options.priceCoefficientDrafts?.[row.id] ?? null
  const base = getOriginalPrice(row)
  return base != null && base !== 0 && row.adjusted_price != null ? row.adjusted_price / base : null
}

const getAdjustedPrice = (row: ReviewedMatchResultOut, options: BuildMatchResultsColumnsOptions) => {
  if (!options.editedPriceIds?.has(row.id) && row.adjusted_price != null) return row.adjusted_price
  const base = getOriginalPrice(row)
  const coefficient = getPriceCoefficient(row, options)
  return base != null && coefficient != null ? Number((base * coefficient).toFixed(2)) : base
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
    { title: '入库品牌', dataIndex: 'brand_code', width: 110, render: (value: string | null) => value ?? '-' },
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
      title: '原价格', dataIndex: 'price', width: 100,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const value = getOriginalPrice(row)
        return value != null ? value.toFixed(2) : '-'
      },
    },
    {
      title: '调整系数', width: 190,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const value = getPriceCoefficient(row, options)
        if (!options.onPriceCoefficientChange || !options.onSavePrice) {
          return value != null ? value.toFixed(2) : <Text type="secondary">不调整</Text>
        }
        const edited = options.editedPriceIds?.has(row.id) ?? false
        const saving = options.savingPriceIds?.has(row.id) ?? false
        return (
          <Space size={6}>
            <InputNumber
              size="small"
              min={0}
              step={0.01}
              precision={2}
              placeholder="不调整"
              value={value}
              onChange={(next) => options.onPriceCoefficientChange?.(row.id, next == null ? null : Number(next))}
              style={{ width: 92 }}
            />
            <Button
              size="small"
              disabled={!edited}
              loading={saving}
              onClick={() => options.onSavePrice?.(row.id)}
            >
              保存
            </Button>
          </Space>
        )
      },
    },
    {
      title: '调整后价格', width: 110,
      render: (_: unknown, row: ReviewedMatchResultOut) => {
        const value = getAdjustedPrice(row, options)
        return value != null ? value.toFixed(2) : '-'
      },
    },
    {
      title: '原销量', dataIndex: 'sales_qty', width: 90,
      render: (value: number | null) => renderNumber(value),
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
      title: '操作', width: 140, fixed: 'right',
      render: (_: unknown, row: ReviewedMatchResultOut) => (
        <Space size={6}>
          <Button type="link" size="small" onClick={() => options.onReselect(row)}>重新选择</Button>
          {row.item_url ? (
            <Link href={row.item_url} target="_blank" rel="noopener noreferrer">URL</Link>
          ) : null}
        </Space>
      ),
    },
  ]
}
