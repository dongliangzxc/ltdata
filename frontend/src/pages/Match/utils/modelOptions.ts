import { listModels } from '../../../services/api'
import type { ModelItem } from '../../../services/api'
import type { ModelLabelSource } from '../../../utils/modelLabel'

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

export function compareModelOptions(a: ModelLabelSource, b: ModelLabelSource): number {
  const key = (model: ModelLabelSource) => model.series?.trim() || model.model_code?.trim() || ''
  return collator.compare(key(a), key(b))
    || collator.compare(a.model_code?.trim() || '', b.model_code?.trim() || '')
    || collator.compare(a.brand_code?.trim() || '', b.brand_code?.trim() || '')
}

// 接口最多返回 2000 条，逐页加载，避免下拉框只显示第一页。
export async function loadAllModelOptions(categoryCode?: string): Promise<ModelItem[]> {
  const models: ModelItem[] = []
  let page = 1
  while (true) {
    const { data } = await listModels({
      page,
      page_size: 2000,
      category_code: categoryCode,
      exclude_placeholder: false,
    })
    models.push(...data.items)
    if (!data.items.length || models.length >= data.total) break
    page += 1
  }
  return models
}
