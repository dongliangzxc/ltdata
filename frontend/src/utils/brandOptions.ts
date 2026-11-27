import { listBrands, type BrandItem } from '../services/api'

// 单字母可能命中很多品牌，必须翻页取完，不能只显示前 50 条。
export async function loadAllBrandOptions(
  keyword?: string,
  isCurrent: () => boolean = () => true,
): Promise<BrandItem[] | undefined> {
  const brands: BrandItem[] = []
  let page = 1
  while (isCurrent()) {
    const { data } = await listBrands({
      keyword: keyword?.trim() || undefined,
      page,
      page_size: 2000,
    })
    if (!isCurrent()) return undefined
    brands.push(...data.items)
    if (!data.items.length || brands.length >= data.total) return brands
    page += 1
  }
  return undefined
}
