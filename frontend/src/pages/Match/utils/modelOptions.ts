import { listModels } from '../../../services/api'
import type { ModelItem } from '../../../services/api'
import { formatModelLabel } from '../../../utils/modelLabel'
import type { ModelLabelSource } from '../../../utils/modelLabel'

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

export function compareModelOptions(a: ModelLabelSource, b: ModelLabelSource): number {
  const key = (model: ModelLabelSource) => model.series?.trim() || model.model_code?.trim() || ''
  return collator.compare(key(a), key(b))
    || collator.compare(a.model_code?.trim() || '', b.model_code?.trim() || '')
    || collator.compare(a.brand_code?.trim() || '', b.brand_code?.trim() || '')
}

type SearchableModel = ModelLabelSource & { id: number; brand_name?: string | null }

const GENERIC_BRAND_CODES = new Set([
  '无品牌', '其他品牌', '其他', '未知品牌', '未知', '未识别品牌', 'UNKNOWN', 'OTHER',
])

function displayLabel(model: SearchableModel): string {
  const brand = (model.brand_code || '').trim()
  const name = (model.model_name || '').trim()
  if (name && GENERIC_BRAND_CODES.has(brand.toUpperCase())) {
    return `${brand ? `[${brand}] ` : ''}${name}`.trim()
  }
  return formatModelLabel(model)
}

export function buildModelSelectOptions(models: SearchableModel[]) {
  return [...models].sort(compareModelOptions).map(model => {
    const label = displayLabel(model)
    return {
      value: model.id,
      label,
      searchText: [label, model.brand_name, model.model_name].filter(Boolean).join(' ').toLocaleLowerCase(),
    }
  })
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

// 缓存只属于当前匹配页实例；成功后保留一分钟，展开和切换商品复用同一品类的数据。
// 同时复用未完成请求，避免反复展开导致多组全量分页并行下载。
export function createModelOptionsLoader(now: () => number = Date.now) {
  const cache = new Map<string, { expiresAt: number; promise: Promise<ModelItem[]> }>()
  return {
    load(categoryCode?: string): Promise<ModelItem[]> {
      const currentTime = now()
      for (const [category, entry] of cache) {
        if (entry.expiresAt <= currentTime) cache.delete(category)
      }
      const key = categoryCode || ''
      const cached = cache.get(key)
      if (cached) return cached.promise
      const entry = {
        expiresAt: Infinity,
        promise: loadAllModelOptions(categoryCode).then(models => {
          if (cache.get(key) === entry) entry.expiresAt = now() + 60_000
          return models
        }, error => {
          if (cache.get(key) === entry) cache.delete(key)
          throw error
        }),
      }
      cache.set(key, entry)
      return entry.promise
    },
    invalidate() {
      cache.clear()
    },
  }
}
