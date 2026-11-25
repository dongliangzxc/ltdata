import type { UrlMappingDeleteScope, UrlMappingFilters } from '../../services/api'

export type UrlMappingSelection = {
  all: boolean
  // 全选时记录取消勾选的 ID，否则记录勾选的 ID；不需要加载其他分页。
  ids: number[]
}

export function isUrlMappingSelected(selection: UrlMappingSelection, id: number): boolean {
  return selection.all ? !selection.ids.includes(id) : selection.ids.includes(id)
}

export function selectUrlMappingRows(selection: UrlMappingSelection, ids: number[], selected: boolean): UrlMappingSelection {
  const next = new Set(selection.ids)
  for (const id of ids) {
    if (selected === selection.all) next.delete(id)
    else next.add(id)
  }
  return { all: selection.all, ids: [...next] }
}

export function countSelectedUrlMappings(selection: UrlMappingSelection, total: number): number {
  return selection.all ? Math.max(0, total - selection.ids.length) : Math.min(total, selection.ids.length)
}

export function buildUrlMappingDeleteScope(filters: UrlMappingFilters, selection: UrlMappingSelection): UrlMappingDeleteScope {
  const ids = Object.freeze([...new Set(selection.ids)])
  return Object.freeze({ ...filters, ...(selection.all ? { exclude_ids: ids } : { include_ids: ids }) })
}

export function buildUrlMappingFilters(filters: UrlMappingFilters): UrlMappingFilters {
  return Object.freeze({
    category_code: filters.category_code,
    platform: filters.platform || undefined,
    brand: filters.brand?.trim() || undefined,
    keyword: filters.keyword?.trim() || undefined,
    year: filters.year,
    month: filters.month,
    ...(filters.start_month != null ? { start_month: filters.start_month } : {}),
    ...(filters.end_month != null ? { end_month: filters.end_month } : {}),
    ...(filters.enabled != null ? { enabled: filters.enabled } : {}),
  })
}

export function describeUrlMappingFilters(filters: UrlMappingFilters, categoryLabel?: string, platformLabel?: string) {
  const descriptions = [
    ['品类', categoryLabel || filters.category_code],
    ['平台', platformLabel || filters.platform || '全部'],
    ['品牌', filters.brand || '全部'],
    ...(filters.start_month != null || filters.end_month != null ? [] : [
      ['年份', filters.year == null ? '全部' : String(filters.year)],
      ['月份', filters.month == null ? '全部' : `${filters.month} 月`],
    ]),
    ['关键词', filters.keyword || '无'],
  ]
  const formatMonth = (month: number) => `${Math.floor(month / 100)}-${String(month % 100).padStart(2, '0')}`
  if (filters.start_month != null || filters.end_month != null) {
    descriptions.push(['确认月份范围', `${filters.start_month == null ? '不限' : formatMonth(filters.start_month)} 至 ${filters.end_month == null ? '不限' : formatMonth(filters.end_month)}`])
  }
  if (filters.enabled != null) descriptions.push(['状态', filters.enabled ? '已启用' : '已禁用'])
  return descriptions
}
