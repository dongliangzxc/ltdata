import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useRequest } from 'ahooks'
import {
  listMatchResults,
  type MatchResultsTab, type PriceFlagFilter, type MatchResultsResponse,
} from '../../services/api'

export interface MatchResultsState {
  page: number
  tab: MatchResultsTab
  cleanJobId?: number
  matchSource: string[]
  priceFlag?: PriceFlagFilter
  keyword: string
}

const DEFAULT_STATE: MatchResultsState = {
  page: 1, tab: 'all', matchSource: [], keyword: '',
}

const VALID_TABS: MatchResultsTab[] = ['all', 'pending_review', 'confirmed']
const VALID_PRICE: PriceFlagFilter[] = ['below', 'above', 'normal', 'none']

function readState(params: URLSearchParams): MatchResultsState {
  const rawTab = params.get('tab') as MatchResultsTab | null
  const rawPrice = params.get('price_flag') as PriceFlagFilter | null
  const rawJob = params.get('job_id')
  const rawPage = params.get('page')
  return {
    page: rawPage ? Math.max(1, parseInt(rawPage, 10) || 1) : 1,
    tab: rawTab && VALID_TABS.includes(rawTab) ? rawTab : 'all',
    cleanJobId: rawJob ? Number(rawJob) || undefined : undefined,
    matchSource: params.getAll('match_source'),
    priceFlag: rawPrice && VALID_PRICE.includes(rawPrice) ? rawPrice : undefined,
    keyword: params.get('keyword') ?? '',
  }
}

function writeState(state: MatchResultsState): URLSearchParams {
  const p = new URLSearchParams()
  if (state.tab !== 'all') p.set('tab', state.tab)
  if (state.cleanJobId != null) p.set('job_id', String(state.cleanJobId))
  state.matchSource.forEach(s => p.append('match_source', s))
  if (state.priceFlag) p.set('price_flag', state.priceFlag)
  if (state.keyword) p.set('keyword', state.keyword)
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
    }).then(r => r.data),
    {
      refreshDeps: [state.page, state.tab, state.cleanJobId,
                    state.matchSource.join(','), state.priceFlag, state.keyword],
      debounceWait: 200,
    },
  )

  return {
    state, setState, reset,
    data: data as MatchResultsResponse | undefined,
    loading, refresh,
  }
}
