import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useRequest } from 'ahooks'
import {
  listMatchResults,
  type CoefficientFilter, type MatchResultsTab, type PriceFlagFilter, type MatchResultsResponse,
} from '../../services/api'

export interface MatchResultsState {
  page: number
  tab: MatchResultsTab
  cleanJobId?: number
  matchSource: string[]
  priceFlag?: PriceFlagFilter
  keyword: string
  platform?: string
  brandKeyword: string
  modelKeyword: string
  coefficientFilter?: CoefficientFilter
}

const DEFAULT_STATE: MatchResultsState = {
  page: 1, tab: 'all', matchSource: [], keyword: '', brandKeyword: '', modelKeyword: '',
}

const VALID_TABS: MatchResultsTab[] = ['all', 'pending_review', 'confirmed']
const VALID_PRICE: PriceFlagFilter[] = ['below', 'above', 'normal', 'none']
const VALID_COEFFICIENT_FILTER: CoefficientFilter[] = ['with', 'without']

function readState(params: URLSearchParams): MatchResultsState {
  const rawTab = params.get('tab') as MatchResultsTab | null
  const rawPrice = params.get('price_flag') as PriceFlagFilter | null
  const rawCoefficientFilter = params.get('coefficient_filter') as CoefficientFilter | null
  const rawJob = params.get('job_id')
  const rawPage = params.get('page')
  return {
    page: rawPage ? Math.max(1, parseInt(rawPage, 10) || 1) : 1,
    tab: rawTab && VALID_TABS.includes(rawTab) ? rawTab : 'all',
    cleanJobId: rawJob ? Number(rawJob) || undefined : undefined,
    matchSource: params.getAll('match_source'),
    priceFlag: rawPrice && VALID_PRICE.includes(rawPrice) ? rawPrice : undefined,
    keyword: params.get('keyword') ?? '',
    platform: params.get('platform') || undefined,
    brandKeyword: params.get('brand_keyword') ?? '',
    modelKeyword: params.get('model_keyword') ?? '',
    coefficientFilter: rawCoefficientFilter && VALID_COEFFICIENT_FILTER.includes(rawCoefficientFilter) ? rawCoefficientFilter : undefined,
  }
}

function writeState(state: MatchResultsState): URLSearchParams {
  const p = new URLSearchParams()
  if (state.tab !== 'all') p.set('tab', state.tab)
  if (state.cleanJobId != null) p.set('job_id', String(state.cleanJobId))
  state.matchSource.forEach(s => p.append('match_source', s))
  if (state.priceFlag) p.set('price_flag', state.priceFlag)
  if (state.keyword) p.set('keyword', state.keyword)
  if (state.platform) p.set('platform', state.platform)
  if (state.brandKeyword) p.set('brand_keyword', state.brandKeyword)
  if (state.modelKeyword) p.set('model_keyword', state.modelKeyword)
  if (state.coefficientFilter) p.set('coefficient_filter', state.coefficientFilter)
  if (state.page > 1) p.set('page', String(state.page))
  return p
}

export function useMatchResultsQuery() {
  const [searchParams, setSearchParams] = useSearchParams()
  const state = useMemo(() => readState(searchParams), [searchParams])

  const setState = (patch: Partial<MatchResultsState>) => {
    const merged: MatchResultsState = { ...state, ...patch }
    // 任何非分页字段变化，页码回到 1
    const nonPageChanged = Object.keys(patch).some(k => k !== 'page')
    if (nonPageChanged) merged.page = 1
    setSearchParams(writeState(merged), { replace: true })
  }

  const reset = () => setSearchParams(writeState(DEFAULT_STATE), { replace: true })

  const { data, loading, refresh } = useRequest(
    () => listMatchResults({
      page: state.page,
      page_size: 20,
      tab: state.tab,
      clean_job_id: state.cleanJobId,
      match_source: state.matchSource.length > 0 ? state.matchSource : undefined,
      price_flag: state.priceFlag,
      keyword: state.keyword || undefined,
      platform: state.platform,
      brand_keyword: state.brandKeyword || undefined,
      model_keyword: state.modelKeyword || undefined,
      coefficient_filter: state.coefficientFilter,
    }).then(r => r.data as MatchResultsResponse),
    {
      refreshDeps: [
        state.page,
        state.tab,
        state.cleanJobId,
        state.matchSource.join(','),
        state.priceFlag,
        state.keyword,
        state.platform,
        state.brandKeyword,
        state.modelKeyword,
        state.coefficientFilter,
      ],
    }
  )

  return { state, setState, reset, data, loading, refresh }
}
