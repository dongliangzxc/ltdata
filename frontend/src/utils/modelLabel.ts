export type ModelLabelSource = {
  brand_code?: string | null
  series?: string | null
  model_code?: string | null
  model_name?: string | null
}

/**
 * 型号下拉/回显文案。
 * - 系列品类（如智能平板）：[品牌] 产品系列 型号码
 * - 无产品系列：[品牌] 型号码
 *
 * 品牌、产品系列、型号码可能来自同源导入而内容相同，相同内容只展示一次，
 * 避免出现「品牌 型号 型号」这类重复。
 */
export function formatModelLabel(m: ModelLabelSource): string {
  const brand = (m.brand_code || '').trim()
  const series = (m.series || '').trim()
  const code = (m.model_code || '').trim()

  const seen = new Set<string>()
  const parts: string[] = []
  const push = (value: string) => {
    if (!value) return
    const key = value.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    parts.push(value)
  }

  if (brand) parts.push(`[${brand}]`)
  if (series) push(series)
  push(code || '待补')
  return parts.join(' ')
}
