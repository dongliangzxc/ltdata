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
  task_created: 20, processed: 20, url_matched: 16, system_filtered: 4,
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
let stateIndex = 0
const jsx = (type, props) => ({ type, props: props ?? {} })
vm.runInNewContext(compiled, {
  exports: exported, URLSearchParams,
  require: name => {
    if (name === 'react') return {
      useMemo: fn => fn(), useEffect: () => {},
      useState: value => {
        const index = stateIndex++
        return [index === 6 ? selectedPlatform : index === 7 ? selectedMonth : value, () => {}]
      },
    }
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' }
    if (name === 'antd') return { Typography: { Text: 'Text' }, ...Object.fromEntries(
      ['Alert', 'Button', 'Card', 'Col', 'Collapse', 'Progress', 'Row', 'Select', 'Space', 'Statistic', 'Table', 'Tag']
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
function statistic(tree, title) {
  return nodes(tree, node => node.type === 'Statistic' && node.props.title === title)[0].props.value
}

const tree = render()
assert.equal(statistic(tree, '已清理'), 20, 'system filtering contributes to displayed completion')
assert.equal(statistic(tree, '系统过滤'), 4, 'filtered records must be visible separately')
assert.equal(statistic(tree, '自动匹配'), 16, 'filtering must not inflate model matches')
assert.equal(statistic(tree, '清理占比'), 100)
const table = nodes(tree, node => node.type === 'Table')[0].props
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
