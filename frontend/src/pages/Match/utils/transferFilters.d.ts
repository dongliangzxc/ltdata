import type { CleanTaskSearchItem } from '../../../services/api'

export interface TransferFilters {
  category?: string
  platform?: string
  month?: number
}

export interface TransferSelectOption<T extends string | number = string | number> {
  value: T
  label: string
}

export interface TransferFilterState {
  categoryOptions: TransferSelectOption<string>[]
  platformOptions: TransferSelectOption<string>[]
  monthOptions: TransferSelectOption<number>[]
  filteredOptions: CleanTaskSearchItem[]
}

export function buildTransferFilterState(
  tasks: CleanTaskSearchItem[],
  filters: TransferFilters,
  categoryLabelMap?: Map<string, string>
): TransferFilterState

export function shouldClearTransferTarget(
  targetId: number | undefined,
  visibleTasks: CleanTaskSearchItem[]
): boolean
