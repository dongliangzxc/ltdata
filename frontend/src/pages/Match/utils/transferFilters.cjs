function uniqueOptions(options) {
  return Array.from(
    new Map(
      (options || [])
        .filter(item => item && item.value)
        .map(item => [item.value, item])
    ).values()
  )
}

function buildTransferFilterState(tasks, filters, categoryLabelMap, optionSources) {
  const labelMap = categoryLabelMap || new Map()

  const categoryOptions = uniqueOptions([
    ...(optionSources && optionSources.categoryOptions ? optionSources.categoryOptions : []),
    ...tasks
      .filter(item => item.category_code)
      .map(item => ({
        value: item.category_code,
        label: item.category_name || labelMap.get(item.category_code) || item.category_code,
      })),
  ])
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))

  const platformOptions = uniqueOptions([
    ...(optionSources && optionSources.platformOptions ? optionSources.platformOptions : []),
    ...tasks
      .map(item => item.platform)
      .filter(Boolean)
      .map(value => ({ value, label: value })),
  ])
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))

  const monthOptions = Array.from(new Set(
    tasks
      .map(item => item.month)
      .filter(value => typeof value === 'number')
  ))
    .sort((a, b) => b - a)
    .map(value => ({ value, label: String(value) }))

  const filteredOptions = tasks.filter(item => {
    if (filters.category && item.category_code !== filters.category) return false
    if (filters.platform && item.platform !== filters.platform) return false
    if (filters.month && item.month !== filters.month) return false
    return true
  })

  return { categoryOptions, platformOptions, monthOptions, filteredOptions }
}

function shouldClearTransferTarget(targetId, visibleTasks) {
  if (!targetId) return false
  return !visibleTasks.some(item => item.id === targetId)
}

function getDefaultTransferFilters(currentTask) {
  return {
    category: undefined,
    platform: undefined,
    month: currentTask && typeof currentTask.month === 'number' ? currentTask.month : undefined,
  }
}

module.exports = {
  buildTransferFilterState,
  getDefaultTransferFilters,
  shouldClearTransferTarget,
}
