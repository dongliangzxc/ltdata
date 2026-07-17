import type { ColumnsType } from 'antd/es/table'

export type CleanPreviewRow = {
  id?: number
  platform?: string | null
  month?: string | number | null
  brand_std?: string | null
  brand?: string | null
  item_name?: string | null
  sales_qty?: number | null
  sales_amount?: number | null
}

export type CleanPreviewResponse = {
  total: number
  items: CleanPreviewRow[]
}

export type TaggedCleanPreviewResponse = CleanPreviewResponse & {
  jobId: number
}

const platformLabelMap: Record<string, string> = {
  jd: '京东',
  tmall: '天猫',
  douyin: '抖音',
}

export const formatNumber = (value?: number | null) => value ?? 0

export const formatText = (value?: string | number | null) => value ?? '-'

export const formatPlatform = (value?: string | null) => value ? (platformLabelMap[value] ?? value) : '-'

export const cleanPreviewColumns: ColumnsType<CleanPreviewRow> = [
  { title: '平台', dataIndex: 'platform', width: 100, render: formatPlatform },
  { title: '月份', dataIndex: 'month', width: 100, render: formatText },
  { title: '标准品牌', dataIndex: 'brand_std', width: 140, render: formatText },
  { title: '原始品牌', dataIndex: 'brand', width: 140, render: formatText },
  { title: '商品名称', dataIndex: 'item_name', ellipsis: true, render: formatText },
  { title: '销量', dataIndex: 'sales_qty', width: 100, render: formatNumber },
  { title: '销售额', dataIndex: 'sales_amount', width: 120, render: formatNumber },
]
