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
  '商品名称', '品牌', '匹配型号', '价格预警', '参考均价', '原销量',
  '修正销量', '调整系数', '调整后销量', '状态', '来源', '重新选择',
]
let previousIndex = -1
for (const label of sharedColumnLabels) {
  const currentIndex = columnDefinition.indexOf(label)
  assert.notEqual(currentIndex, -1, `columns should include ${label}`)
  assert.ok(currentIndex > previousIndex, `${label} should appear after previous shared column`)
  previousIndex = currentIndex
}
assert.notEqual(cols.indexOf('renderMatchStatus'), -1, 'columns should render Chinese match status labels')
assert.notEqual(cols.indexOf('renderMatchSource'), -1, 'columns should render match source labels')
// URL query 双向同步 key
assert.notEqual(hook.indexOf("params.get('tab')"), -1)
assert.notEqual(hook.indexOf("params.getAll('match_source')"), -1)
assert.notEqual(hook.indexOf("params.get('job_id')"), -1)
// 筛选变化时 page 复位
assert.notEqual(hook.indexOf('nonPageChanged'), -1, 'non-page changes should reset page')

console.log('MatchResults layout tests passed')
