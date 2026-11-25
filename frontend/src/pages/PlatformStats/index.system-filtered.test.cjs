const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
}).outputText
const base = {
  month: 202610, category_code: 'router', category_name: '路由器', dispatched: 10,
  task_created: 10, task_count: 1, processed: 10, matched: 8, url_matched: 8,
  auto_matched: 0, confirmed: 0, excluded_ignored: 0, system_filtered: 2,
  pending: 0, published: 0, last_processed_at: '2026-11-24 09:00:00', completed_at: '2026-11-24 09:00:00',
}
const progress = {
  ...base, dispatchable: 20, dispatched: undefined, uploaded_rows: 20,
  task_created: 20, processed: 20, matched: 16, url_matched: 16, system_filtered: 4,
  not_task_created: 0, not_processed: 0, task_no_result: 0,
  months: [], categories: [{ ...base, platform: 'jd' }, {
    ...base, platform: 'tmall', last_processed_at: '2026-11-24 10:00:00', completed_at: '2026-11-24 10:00:00',
  }],
}
const data = {
  progress, categories: [], monthly: [], sources: [],
  upload: { file_rows: 20, dedup_skipped_rows: 0 }, clean: {}, match: { text_only: 0, disputed: 0 },
  assets: { models: 0, brands: 0, url_mapping_sources: [] },
}
const exported = {}
let selectedMonth
let selectedPlatform = 'all'
let selectedCategories
let initialCategories
let stateIndex = 0
const jsx = (type, props) => ({ type, props: props ?? {} })
vm.runInNewContext(compiled, {
  exports: exported, URLSearchParams,
  require: name => {
    if (name === 'react') return {
      useMemo: fn => fn(), useEffect: () => {},
      useState: value => {
        const index = stateIndex++
        if (index === 5) initialCategories = value
        return [index === 5 ? selectedCategories : index === 6 ? selectedPlatform : index === 7 ? selectedMonth : value,
          next => { if (index === 5) selectedCategories = next }]
      },
    }
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' }
    if (name === 'antd') return { Typography: { Text: 'Text' }, ...Object.fromEntries(
      ['Alert', 'Button', 'Card', 'Checkbox', 'Col', 'Collapse', 'Progress', 'Row', 'Select', 'Space', 'Statistic', 'Table', 'Tag']
        .map(component => [component, component]),
    ) }
    if (name === '@ant-design/icons') return { ReloadOutlined: 'ReloadOutlined' }
    if (name === 'ahooks') return { useRequest: () => ({ data, loading: false, refresh: () => {} }) }
    if (name === '../../services/api') return {}
    throw new Error(`Unexpected import: ${name}`)
  },
})
function render() {
  stateIndex = 0
  return exported.default()
}
function nodes(tree, predicate, found = []) {
  if (Array.isArray(tree)) tree.forEach(node => nodes(node, predicate, found))
  else if (tree && typeof tree === 'object') {
    if (predicate(tree)) found.push(tree)
    nodes(tree.props?.children, predicate, found)
  }
  return found
}
function overviewProgress(tree, label) {
  return nodes(tree, node => node.type === 'Progress' && node.props['aria-label'] === label)[0].props.percent
}
function matchingRates(tree) {
  return [overviewProgress(tree, '匹配进度'), statistic(tree, '匹配进度')]
}
function statistic(tree, title) {
  return nodes(tree, node => node.type === 'Statistic' && node.props.title === title)[0].props.value
}

const tree = render()
assert.equal(statistic(tree, '已清理'), 20, 'system filtering contributes to displayed completion')
assert.equal(statistic(tree, '系统过滤'), 4, 'filtered records must be visible separately')
assert.equal(statistic(tree, '自动匹配'), 16, 'filtering must not inflate model matches')
assert.equal(statistic(tree, '清理占比'), 100)
assert.equal(statistic(tree, '已匹配'), 16)
assert.equal(statistic(tree, '匹配进度'), 80, 'system filtering completes cleaning without increasing matching progress')
assert.equal(overviewProgress(tree, '处理进度'), 100, 'processing progress must remain separately visible')
assert.equal(overviewProgress(tree, '匹配进度'), 80, 'matching progress supplements processing progress')
const overviewCard = nodes(tree, node => node.type === 'Card' && node.props.title === '处理进度总览')[0]
const originalSummaryRow = nodes(overviewCard, node => node.type === 'Row')[0]
assert.deepEqual(nodes(originalSummaryRow, node => node.type === 'Statistic').map(node => node.props.title),
  ['上传入库数据总量', '值得分发（分发条目）', '已清理', '清理占比'], 'preserve the original four overview metrics')
const detailCard = nodes(tree, node => node.type === 'Card' && node.props.title === '处理进度明细（月份 / 品类 / 平台）')[0]
const originalDetailRow = nodes(detailCard, node => node.type === 'Row')[0]
assert.deepEqual(nodes(originalDetailRow, node => node.type === 'Statistic').map(node => node.props.title),
  ['分发条数', '已入任务条数', '清洗任务数', '未入任务条数', '已清理', '未清理', '当前待处理', '整体清洗进度'],
  'matching progress must not displace original processing summary metrics')
const table = nodes(tree, node => node.type === 'Table')[0].props
const matchColumn = table.columns.find(col => col.key === 'match_rate')
assert.equal(matchColumn.title, '匹配进度')
assert.equal(matchColumn.render(null, table.dataSource[0]).props.percent, 80)
assert.equal(matchColumn.render(null, { ...base, dispatched: 20, task_created: 10, matched: 5 }).props.percent, 25,
  'matching progress uses dispatched rows, including rows not yet in tasks')
assert.equal(matchColumn.render(null, { ...base, dispatched: 0 }).props.children, '无分发数据')
assert.ok(matchColumn.sorter({ ...base, matched: 100, dispatched: 1000 }, { ...base, matched: 1, dispatched: 2 }) < 0,
  'matching progress sorts by ratio rather than raw matches')
assert.ok(table.columns.some(col => col.key === 'task_rate'), 'task processing progress remains in the table')
assert.ok(table.columns.some(col => col.key === 'overall_rate'), 'overall processing progress remains in the table')
assert.equal(table.dataSource.length, 1, 'all-platform view aggregates the category')
assert.equal(table.dataSource[0].system_filtered, 4, 'aggregation must sum both platforms')
assert.equal(table.dataSource[0].completed_at, '2026-11-24 10:00:00', 'completion uses the latest time across platforms')
progress.categories[1].dispatched = 11
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource[0].completed_at, null,
  'one completed platform must not make an incomplete aggregate look finished')
progress.categories[1].dispatched = 10
const column = table.columns.find(col => col.dataIndex === 'system_filtered')
assert.equal(column.title, '系统过滤')
assert.equal(column.render(4), '4')
assert.equal(column.render(undefined), '0', 'old cached payloads remain renderable')

selectedPlatform = 'jd'
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource[0].system_filtered, 2)
selectedMonth = 202609
assert.equal(statistic(render(), '系统过滤'), 0, 'empty months must not retain the total filter count')
assert.equal(statistic(render(), '已清理'), 0)

// During rolling deployment, the prior API/cache may omit the new field.
selectedMonth = undefined
selectedPlatform = 'all'
delete progress.system_filtered
progress.categories.forEach(row => { delete row.system_filtered })
assert.equal(statistic(render(), '系统过滤'), 0)
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource[0].system_filtered, 0)

// A transferred source item is handled there, while its model review continues elsewhere.
progress.transferred_out = 2
progress.categories.forEach(row => { row.transferred_out = 1 })
assert.equal(statistic(render(), '已转出'), 2)
const transferredTable = nodes(render(), node => node.type === 'Table')[0].props
assert.equal(transferredTable.dataSource[0].transferred_out, 2)
assert.equal(transferredTable.columns.find(col => col.dataIndex === 'transferred_out').render(1), '1')
selectedPlatform = 'jd'
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource[0].transferred_out, 1)
delete progress.transferred_out
assert.equal(statistic(render(), '已转出'), 0, 'rolling deployment remains compatible with the prior API')

// The category selector affects every progress metric and the detail table together.
progress.uploaded_rows = 100
progress.categories = [
  { ...base, platform: 'jd', dispatched: 20, task_created: 15, processed: 10, pending: 3,
    matched: 7, url_matched: 4, auto_matched: 2, confirmed: 1, excluded_ignored: 1,
    system_filtered: 1, transferred_out: 1, published: 8 },
  { ...base, platform: 'tmall', dispatched: 10, task_created: 8, processed: 5, pending: 2,
    matched: 3, url_matched: 1, auto_matched: 1, confirmed: 1, excluded_ignored: 1,
    system_filtered: 0, transferred_out: 1, published: 4 },
  { ...base, category_code: 'camera', category_name: '相机', platform: 'jd', dispatched: 50 },
  { ...base, month: 202609, platform: 'jd', dispatched: 5, task_created: 5,
    processed: 3, matched: 3, url_matched: 3, system_filtered: 0, pending: 1, published: 2 },
]
selectedPlatform = 'all'
selectedMonth = undefined
const selector = () => nodes(render(), node => node.type === 'Select'
  && node.props['aria-label'] === '筛选处理进度品类')[0].props
assert.equal(selector().mode, 'multiple')
assert.equal(JSON.stringify(selector().value.slice().sort()), JSON.stringify(['camera', 'router']),
  'categories loaded asynchronously must all start selected')
assert.equal(selector().maxTagPlaceholder(), '全部品类（2）')
selector().onChange(['router'])
assert.equal(statistic(render(), '值得分发（分发条目）'), 35)
assert.equal(statistic(render(), '已清理'), 18)
assert.equal(statistic(render(), '未入任务条数'), 7)
assert.equal(statistic(render(), '未清理'), 17)
assert.equal(statistic(render(), '已入任务未出结果'), 4)
assert.equal(statistic(render(), '自动匹配'), 11)
assert.equal(statistic(render(), '人工确认'), 2)
assert.equal(statistic(render(), '已转出'), 2)
assert.equal(statistic(render(), '系统过滤'), 1)
assert.equal(statistic(render(), '清理占比'), 51.4)
assert.equal(overviewProgress(render(), '处理进度'), 51.4)
assert.deepEqual(matchingRates(render()), [37.1, 37.1], 'overview and detail match ratios sum counts before dividing')
assert.equal(statistic(render(), '已匹配'), 13)
assert.equal(statistic(render(), '上传入库数据总量（全部品类）'), 100,
  'uploaded raw rows have no category dimension and must be labelled accordingly')
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource.length, 2)
assert.ok(nodes(render(), node => node.type === 'Table')[0].props.dataSource.every(row => row.category_code === 'router'))

selectedMonth = 202610
assert.equal(statistic(render(), '值得分发（分发条目）'), 30, 'month and category filters combine')
assert.equal(statistic(render(), '已清理'), 15)
assert.equal(statistic(render(), '匹配进度'), 33.3)
selectedPlatform = 'jd'
assert.equal(statistic(render(), '值得分发（分发条目）'), 30, 'detail platform view does not change overview scope')
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource.length, 1)
assert.deepEqual(matchingRates(render()), [33.3, 35], 'detail matching progress follows the platform filter')

selector().onChange([])
assert.equal(statistic(render(), '值得分发（分发条目）'), 0, 'clearing categories must not silently select all')
assert.equal(statistic(render(), '已清理'), 0)
assert.equal(statistic(render(), '清理占比'), 0)
assert.equal(overviewProgress(render(), '处理进度'), 0)
assert.equal(overviewProgress(render(), '匹配进度'), 0)
assert.equal(statistic(render(), '匹配进度'), 0)
assert.equal(statistic(render(), '已匹配'), 0)
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource.length, 0)
const selectAll = nodes(selector().dropdownRender('menu'), node => node.type === 'Checkbox')[0].props
assert.equal(selectAll.checked, false)
selectAll.onChange({ target: { checked: true } })
assert.equal(selectedCategories, undefined, 'select all restores the unfiltered scope')
selector().onChange(['router', 'camera'])
assert.equal(selectedCategories, undefined, 'manually selecting every category also restores all mode')
progress.categories.push({ ...base, category_code: 'speaker', category_name: '音箱', platform: 'jd' })
assert.ok(selector().value.includes('speaker'), 'refreshing all mode automatically includes new categories')
selector().onChange(['router', 'speaker'])
assert.equal(statistic(render(), '值得分发（分发条目）'), 40, 'multiple selected categories are summed within the chosen month')
assert.equal(statistic(render(), '已清理'), 25)
assert.equal(selector().maxTagPlaceholder(), '已选 2 个品类')
const partialSelectAll = nodes(selector().dropdownRender('menu'), node => node.type === 'Checkbox')[0].props
assert.equal(partialSelectAll.checked, false)
assert.equal(partialSelectAll.indeterminate, true)

// New visits use exactly the 17 categories highlighted by the user.
const expectedDefaults = ['camera', 'smartwatch', 'power_bank', 'tablet', 'router', 'kids_smartwatch',
  'smart_speaker', 'dict_pen', 'soundbar', 'smart_lock', 'dashcam', 'projector', 'edu_tablet',
  'vrar', 'video_doorbell', 'smart_scale', 'eye_protection_lamp']
assert.equal(JSON.stringify([...initialCategories].sort()), JSON.stringify([...expectedDefaults].sort()))
selectedCategories = [...initialCategories]
selectedMonth = undefined
selectedPlatform = 'all'
progress.categories = []
assert.equal(selector().value.length, 0, 'do not show unavailable defaults while progress data loads')
progress.categories = expectedDefaults.map(code => ({ ...base, category_code: code, category_name: code, platform: 'jd' }))
progress.categories.push(...['headphone', 'bt_speaker', 'laptop'].map(code => ({
  ...base, category_code: code, category_name: code, platform: 'jd', dispatched: 1000, processed: 500,
})))
assert.equal(selector().value.length, 17, 'default categories become selected when async data arrives')
assert.equal(selector().maxTagPlaceholder(), '已选 17 个品类')
assert.ok(!selector().value.includes('headphone') && !selector().value.includes('bt_speaker'))
assert.equal(statistic(render(), '值得分发（分发条目）'), 170, 'default denominator excludes unselected categories')
assert.equal(statistic(render(), '已清理'), 170)
assert.equal(overviewProgress(render(), '处理进度'), 100)
assert.equal(overviewProgress(render(), '匹配进度'), 80)
assert.equal(nodes(render(), node => node.type === 'Table')[0].props.dataSource.length, 17)
selector().onChange([...expectedDefaults, 'headphone'])
assert.equal(statistic(render(), '值得分发（分发条目）'), 1170, 'users can add categories outside the defaults')
assert.equal(overviewProgress(render(), '处理进度'), 57.3)
selector().onChange([])
assert.equal(statistic(render(), '值得分发（分发条目）'), 0, 'clearing must not restore defaults')
const defaultCheckbox = nodes(selector().dropdownRender('menu'), node => node.type === 'Checkbox')[0].props
defaultCheckbox.onChange({ target: { checked: true } })
assert.equal(selector().value.length, 20, 'select all includes categories outside the defaults')
selectedCategories = [...initialCategories]
progress.categories = progress.categories.filter(row => row.category_code !== 'smart_scale')
assert.equal(selector().value.length, 16, 'missing categories do not create phantom selection tags')
console.log('platform stats filtering and accounting tests passed')
