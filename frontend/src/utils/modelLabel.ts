export type ModelLabelSource = {
  brand_code?: string | null
  series?: string | null
  model_code?: string | null
  model_name?: string | null
}

/**
 * 型号下拉/回显文案。
 * - 系列品类（如智能平板）：[品牌] 产品系列 型号码
 * - 其它品类：[品牌] 型号码 型号名称（与原展示保持一致）
 */
export function formatModelLabel(m: ModelLabelSource): string {
  const brand = m.brand_code || '-'
  const series = (m.series || '').trim()
  if (series) {
    return `[${brand}] ${series} ${m.model_code || '待补'}`
  }
  return `[${brand}] ${m.model_code || '待补'}${m.model_name ? ' ' + m.model_name : ''}`
}
