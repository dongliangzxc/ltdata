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

const app = fs.readFileSync(path.resolve(dir, '../../App.tsx'), 'utf8')
const layout = fs.readFileSync(path.resolve(dir, '../../components/Layout/index.tsx'), 'utf8')

assert.match(app, /path="\/match-results"[^\n]*<MatchResultsPage/, 'match-results route should render MatchResultsPage')
assert.match(layout, /key: '\/match-results'[^\n]*label: '匹配结果'/, 'sidebar should expose 匹配结果')
assert.match(idx, /匹配结果/, 'match results page should render 匹配结果 title')

console.log('MatchResults layout tests passed')

assert.notEqual(idx.indexOf('placeholder="平台"'), -1, 'page should expose platform filter')
assert.notEqual(idx.indexOf('placeholder="品牌"'), -1, 'page should expose brand filter')
assert.notEqual(idx.indexOf('placeholder="匹配型号"'), -1, 'page should expose matched model filter')
assert.notEqual(idx.indexOf('placeholder="调整系数"'), -1, 'page should expose coefficient filter')
assert.notEqual(idx.indexOf('有调整系数'), -1, 'coefficient filter should include with option')
assert.notEqual(idx.indexOf('无调整系数'), -1, 'coefficient filter should include without option')
assert.notEqual(hook.indexOf("params.get('platform')"), -1, 'query hook should read platform from URL')
assert.notEqual(hook.indexOf("params.get('brand_keyword')"), -1, 'query hook should read brand keyword from URL')
assert.notEqual(hook.indexOf("params.get('model_keyword')"), -1, 'query hook should read model keyword from URL')
assert.notEqual(hook.indexOf("params.get('coefficient_filter')"), -1, 'query hook should read coefficient filter from URL')
assert.notEqual(hook.indexOf("p.set('platform', state.platform)"), -1, 'query hook should write platform to URL')
assert.notEqual(hook.indexOf("p.set('brand_keyword', state.brandKeyword)"), -1, 'query hook should write brand keyword to URL')
assert.notEqual(hook.indexOf("p.set('model_keyword', state.modelKeyword)"), -1, 'query hook should write model keyword to URL')
assert.notEqual(hook.indexOf("p.set('coefficient_filter', state.coefficientFilter)"), -1, 'query hook should write coefficient filter to URL')
assert.notEqual(hook.indexOf('platform: state.platform'), -1, 'query hook should send platform to API')
assert.notEqual(hook.indexOf('brand_keyword: state.brandKeyword'), -1, 'query hook should send brand keyword to API')
assert.notEqual(hook.indexOf('model_keyword: state.modelKeyword'), -1, 'query hook should send model keyword to API')
assert.notEqual(hook.indexOf('coefficient_filter: state.coefficientFilter'), -1, 'query hook should send coefficient filter to API')
