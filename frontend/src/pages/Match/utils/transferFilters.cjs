function buildTransferFilterState(tasks, filters, categoryLabelMap) {
  const labelMap = categoryLabelMap || new Map()

  const categoryOptions = Array.from(
    new Map(
      tasks
        .filter(item => item.category_code)
        .map(item => [
          item.category_code,
          item.category_name || labelMap.get(item.category_code) || item.category_code,
        ])
    ).entries()
  )
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))

  const platformOptions = Array.from(new Set(
    tasks
      .map(item => item.platform)
      .filter(Boolean)
  ))
    .sort((a, b) => a.localeCompare(b))
    .map(value => ({ value, label: value }))

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

module.exports = {
  buildTransferFilterState,
  shouldClearTransferTarget,
}
