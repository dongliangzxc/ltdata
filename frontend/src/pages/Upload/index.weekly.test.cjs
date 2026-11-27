const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const tree = ts.createSourceFile('index.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function load(name, scope = {}) {
  let node
  function visit(item) {
    if (ts.isVariableDeclaration(item) && item.name.getText(tree) === name) node = item.initializer
    ts.forEachChild(item, visit)
  }
  visit(tree)
  assert(node, `Missing real page helper ${name}`)
  const code = ts.transpileModule(`exports.run = ${node.getText(tree)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, ...scope })
  return exports.run
}
const group = load('groupUploadHistory')
const file = { id: 1, filename: 'one.xlsx', batch_key: 'batch', period_type: 'week', weeks: [3, 1], row_count: 2 }
const weeks = group([file, { ...file, id: 2, weeks: [5, 3], row_count: 4 }])[0]
assert.equal(weeks.period_label, '周度：第1周、第3周、第5周')
assert.equal(weeks.row_count, 6)
const mixed = group([file, { ...file, id: 2, period_type: 'month', weeks: [] }])[0]
assert.equal(mixed.period_label, '月度 / 周度')
assert.equal(group([{ ...file, batch_key: null }])[0].period_type, 'week')

const fields = load('STANDARD_FIELD_OPTIONS')
const required = load('REQUIRED_FIELDS')
const mapping = load('buildAutoMapping', {
  STANDARD_FIELD_OPTIONS: fields,
  REQUIRED_FIELDS: required,
  inferredFieldSet: load('inferredFieldSet'),
})
for (const label of ['week', '周', '周次', '周度']) {
  const result = mapping({ columns: ['item_id', 'month', 'platform', 'item_name', 'sales_qty', 'sales_amount', 'price', label] })
  assert.equal(result.mapping[label], 'week')
  assert.equal(result.missing.length, 0)
}
console.log('Weekly upload: week aliases and mixed/monthly/weekly batch history verified')
