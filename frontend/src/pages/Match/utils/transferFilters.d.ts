export interface TransferTaskLike {
  id: number
  category_code?: string | null
  category_name?: string | null
  platform?: string | null
  month?: number | null
}

export interface TransferFilters {
  category?: string
  platform?: string
  month?: number
}

export interface TransferSelectOption<T extends string | number = string | number> {
  value: T
  label: string
}

export interface TransferFilterState<TTask extends TransferTaskLike = TransferTaskLike> {
  categoryOptions: TransferSelectOption<string>[]
  platformOptions: TransferSelectOption<string>[]
  monthOptions: TransferSelectOption<number>[]
  filteredOptions: TTask[]
}

export function buildTransferFilterState<TTask extends TransferTaskLike>(
  tasks: TTask[],
  filters: TransferFilters,
  categoryLabelMap?: Map<string, string>
): TransferFilterState<TTask>

export function shouldClearTransferTarget<TTask extends TransferTaskLike>(
  targetId: number | undefined,
  visibleTasks: TTask[]
): boolean
