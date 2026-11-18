import type { CleanAccounting, CleanMatchedItem } from '../../services/api'

export function formatCleanAccounting(value: CleanAccounting) {
  const { input_count: input, retained_count: kept, filtered_count: filtered, duplicate_count: duplicates } = value
  const current = `输入 ${input} 条；保留 ${kept} 条；过滤 ${filtered} 条；已记录重复 ${duplicates} 条`
  if (value.status === 'balanced') {
    return { type: 'success' as const,
      message: `输入 ${input} 条 = 保留 ${kept} 条 + 过滤 ${filtered} 条 + 重复 ${duplicates} 条`,
      description: '按当前清洗结果对账，过滤数不包含已恢复记录。' }
  }
  if (value.status === 'processing') {
    return { type: 'info' as const, message: current, description: '任务正在处理，完成后再核对；当前仅统计已提交结果。' }
  }
  if (value.status === 'failed') {
    return { type: 'warning' as const, message: current, description: '任务失败或中断，当前仅展示已提交结果，重试完成后再核对。' }
  }
  if (value.status === 'legacy') {
    return { type: 'info' as const, message: current, description: '历史任务未完整记录去重明细，仅展示已记录部分，不根据差额推算重复。' }
  }
  const difference = value.difference ?? 0
  return { type: 'warning' as const, message: current,
    description: difference >= 0 ? `还有 ${difference} 条未对上，请核查清洗明细。` : `结果合计比输入多 ${-difference} 条，请核查清洗明细。` }
}

export function formatDuplicateBasis(row: Pick<CleanMatchedItem, 'dedup_basis' | 'dedup_key'>): string {
  if (row.dedup_basis !== 'item_id_month_shop' || !row.dedup_key) return '去重依据未记录'
  const key = row.dedup_key
  const show = (value: unknown) => value == null ? '（空）' : JSON.stringify(value)
  return `商品ID ${show(key.item_id)}、月份 ${show(key.month)}、店铺 ${show(key.shop_name)} 完全相同`
}
