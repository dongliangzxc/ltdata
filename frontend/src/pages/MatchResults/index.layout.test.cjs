const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const dir = __dirname
const idx = fs.readFileSync(path.join(dir, 'index.tsx'), 'utf8')
const cols = fs.readFileSync(path.join(dir, 'columns.tsx'), 'utf8')
const hook = fs.readFileSync(path.join(dir, 'useMatchResultsQuery.ts'), 'utf8')

// 页面挂载 ReselectModal
assert.notEqual(idx.indexOf('<ReselectModal'), -1, 'page should mount ReselectModal')
// 三 Tab
assert.notEqual(idx.indexOf("key: 'all'"), -1, 'tab all')
assert.notEqual(idx.indexOf("key: 'pending_review'"), -1, 'tab pending_review')
assert.notEqual(idx.indexOf("key: 'confirmed'"), -1, 'tab confirmed')
// Badge 计数
assert.notEqual(idx.indexOf('counts.all'), -1, 'badge all')
assert.notEqual(idx.indexOf('counts.pending_review'), -1, 'badge pending_review')
assert.notEqual(idx.indexOf('counts.confirmed'), -1, 'badge confirmed')
// 筛选栏字段
assert.notEqual(idx.indexOf('全部任务（未选时展示全库）'), -1, 'job select placeholder')
assert.notEqual(idx.indexOf('匹配来源（多选）'), -1, 'source select placeholder')
assert.notEqual(idx.indexOf('按商品名称搜索'), -1, 'keyword search placeholder')
// 未选任务提示
assert.notEqual(idx.indexOf('未选任务时展示全库最新结果'), -1, 'no-job hint')
// 表格列使用完整共享列集
const columnsReturnIndex = cols.indexOf('return [')
assert.notEqual(columnsReturnIndex, -1, 'columns should return table column definitions')
const columnDefinition = cols.slice(columnsReturnIndex)
const sharedColumnLabels = [
  '商品名称', '入库品牌', '匹配型号', '价格预警', '原价格', '现价格',
  '原销量', '调整系数', '调整后销量', '重新选择', 'URL',
]
let previousIndex = -1
for (const label of sharedColumnLabels) {
  const currentIndex = columnDefinition.indexOf(label)
  assert.notEqual(currentIndex, -1, `columns should include ${label}`)
  assert.ok(currentIndex > previousIndex, `${label} should appear after previous shared column`)
  previousIndex = currentIndex
}
for (const removedLabel of ['宝贝名称', '参考均价', '修正销量']) {
  assert.equal(columnDefinition.indexOf(removedLabel), -1, `columns should not include old label ${removedLabel}`)
}
assert.notEqual(cols.indexOf('onPriceChange'), -1, 'columns should expose an editable current price input')
assert.notEqual(cols.indexOf('onSavePrice'), -1, 'columns should save current price edits')
assert.notEqual(cols.indexOf('adjusted_price'), -1, 'columns should bind current price to adjusted_price')
// URL query 双向同步 key
assert.notEqual(hook.indexOf("params.get('tab')"), -1)
assert.notEqual(hook.indexOf("params.getAll('match_source')"), -1)
assert.notEqual(hook.indexOf("params.get('job_id')"), -1)
// 筛选变化时 page 复位
assert.notEqual(hook.indexOf('nonPageChanged'), -1, 'non-page changes should reset page')

console.log('MatchResults layout tests passed')

const app = fs.readFileSync(path.resolve(dir, '../../App.tsx'), 'utf8')
const layout = fs.readFileSync(path.resolve(dir, '../../components/Layout/index.tsx'), 'utf8')

assert.match(app, /path="\/data-adjustment"[^\n]*<MatchResultsPage/, 'data adjustment route should render MatchResultsPage')
assert.match(app, /path="\/match-results"[^\n]*<MatchResultsPage/, 'legacy match-results route should keep rendering MatchResultsPage')
assert.match(layout, /key: '\/data-adjustment'[^\n]*label: '数据调整'/, 'sidebar should expose 数据调整')
assert.equal(layout.includes("key: '/match-results'"), false, 'sidebar should not expose 匹配结果 as a separate menu item')
assert.match(idx, /数据调整/, 'match results page should render 数据调整 title')
