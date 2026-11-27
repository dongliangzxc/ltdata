const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const tree = ts.createSourceFile('index.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let pendingTable
function visit(node) {
  if (ts.isJsxSelfClosingElement(node) && node.typeArguments?.some(t => t.getText(tree) === 'PendingUploadFile')) pendingTable = node
  ts.forEachChild(node, visit)
}
visit(tree)
assert(pendingTable, 'Pending upload table must be rendered')
const code = ts.transpileModule(`exports.table = (${pendingTable.getText(tree)})`, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText
const output = {}
vm.runInNewContext(code, {
  exports: output, Table: 'Table', pendingFiles: [{ uid: 'one', filename: 'a'.repeat(300) + '.xlsx' }],
  require: () => ({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }),
})
const props = output.table.props
const totalColumnWidth = props.columns.reduce((total, column) => total + (column.width || 0), 0)
assert(totalColumnWidth > 1400, 'Exercise the wide pending-file table')
assert(props.scroll?.x >= totalColumnWidth, 'All pending columns must fit within an internal scrolling table')
assert(props.columns.every(c => c.width > 0), 'Long filenames cannot force an unbounded flexible column')
const actions = props.columns.find(c => c.title === '操作')
assert.equal(actions.fixed, 'right', 'Configuration and removal remain reachable when the table is scrolled')
assert.equal(props.dataSource[0].filename.length, 305, 'Long filenames remain intact in the source data')
console.log('Upload layout: bounded scrolling contains all columns, long filenames and reachable actions')
