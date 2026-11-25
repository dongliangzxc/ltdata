const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

const moduleUnderTest = { exports: {} }
const source = fs.readFileSync(path.join(__dirname, 'filters.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
new Function('exports', compiled)(moduleUnderTest.exports)
const {
  buildUrlMappingFilters, describeUrlMappingFilters, buildUrlMappingDeleteScope,
  isUrlMappingSelected, selectUrlMappingRows, countSelectedUrlMappings,
} = moduleUnderTest.exports

const input = { category_code: 'xr', platform: 'jd', brand: '  SONY  ', keyword: ' A1 ', year: 2026, month: 10 }
const snapshot = buildUrlMappingFilters(input)
assert.deepEqual(snapshot, { category_code: 'xr', platform: 'jd', brand: 'SONY', keyword: 'A1', year: 2026, month: 10 })
input.platform = 'tmall'
input.brand = 'JBL'
assert.equal(snapshot.platform, 'jd', '弹窗预览后的筛选更改不能改变本次删除范围')
assert.equal(snapshot.brand, 'SONY')
assert.equal(Object.isFrozen(snapshot), true)
assert.deepEqual(describeUrlMappingFilters(snapshot, 'XR和智能眼镜', '京东 (JD)'), [
  ['品类', 'XR和智能眼镜'], ['平台', '京东 (JD)'], ['品牌', 'SONY'],
  ['年份', '2026'], ['月份', '10 月'], ['关键词', 'A1'],
])
const empty = buildUrlMappingFilters({ category_code: 'xr', brand: '  ', keyword: ' ' })
assert.equal(empty.brand, undefined)
assert.equal(empty.keyword, undefined)
assert.deepEqual(describeUrlMappingFilters(empty), [
  ['品类', 'xr'], ['平台', '全部'], ['品牌', '全部'], ['年份', '全部'], ['月份', '全部'], ['关键词', '无'],
])

let selection = { all: true, ids: [] }
assert.equal(countSelectedUrlMappings(selection, 1005), 1005, '默认全选应涵盖全部分页')
assert.equal(isUrlMappingSelected(selection, 1005), true)
selection = selectUrlMappingRows(selection, [1], false)
selection = selectUrlMappingRows(selection, [21], false)
assert.equal(isUrlMappingSelected(selection, 1), false, '第一页取消后翻页再回来应保持取消')
assert.equal(isUrlMappingSelected(selection, 21), false)
assert.equal(isUrlMappingSelected(selection, 1005), true, '其他分页仍默认选中')
assert.equal(countSelectedUrlMappings(selection, 1005), 1003)
const scope = buildUrlMappingDeleteScope(snapshot, selection)
assert.deepEqual(scope.exclude_ids, [1, 21])
assert.equal(scope.include_ids, undefined)
assert.equal(Object.isFrozen(scope.exclude_ids), true, '弹窗中的排除列表也应固定')
selection = selectUrlMappingRows(selection, [1], true)
assert.equal(countSelectedUrlMappings(selection, 1005), 1004)
assert.deepEqual(scope.exclude_ids, [1, 21], '预览后更改勾选不能改变已预览的排除列表')

// 当前页全选/取消只改变该页，不覆盖其他页。
selection = selectUrlMappingRows(selection, [1, 2, 3], false)
assert.deepEqual(new Set(selection.ids), new Set([21, 1, 2, 3]))
selection = selectUrlMappingRows(selection, [1, 2, 3], true)
assert.deepEqual(selection.ids, [21])

selection = { all: false, ids: [] }
assert.equal(countSelectedUrlMappings(selection, 1005), 0, '取消跨页全选后不应选中任何记录')
selection = selectUrlMappingRows(selection, [1, 1, 21], true)
assert.equal(countSelectedUrlMappings(selection, 1005), 2)
assert.equal(isUrlMappingSelected(selection, 999), false)
assert.deepEqual(buildUrlMappingDeleteScope(snapshot, selection).include_ids, [1, 21])
selection = selectUrlMappingRows(selection, [1], false)
assert.deepEqual(selection.ids, [21])
assert.deepEqual(buildUrlMappingDeleteScope(snapshot, { all: false, ids: [] }).include_ids, [], '空勾选必须显式表示空集合，不能退化成全选')

const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
assert.match(page, /getUrlMappingCategoryCount\(filters\)/, '预览须传全部筛选条件')
assert.match(page, /bulkDeleteUrlMappings\(bulkFilters, bulkCount\)/, '删除须使用预览快照及已确认数量')
assert.match(page, /disabled: bulkLoading \|\| bulkCount == null \|\| bulkCount <= 0/, '统计失败或为空时不能提交删除')
assert.match(page, /seq !== bulkCountSeqRef.current/, '关闭/重开弹窗后须丢弃旧计数响应')
assert.match(page, /buildUrlMappingDeleteScope\(mappingFilters, selection\)/, '预览必须带上跨页勾选范围')
assert.match(page, /\[filterKey\]/, '更改筛选条件应重置勾选状态')
assert.match(page, /updateSelection\(\{ all: false, ids: \[\] \}\)/, '删除成功后保留下来的记录不应被自动重新选中')
assert.doesNotMatch(page, /不受关键词 \/ 平台/, '弹窗不应再说明忽略当前筛选条件')
console.log('filtered URL mapping delete tests passed')
