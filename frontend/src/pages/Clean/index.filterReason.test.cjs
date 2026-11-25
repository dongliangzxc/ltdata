const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')
const calls = []
const source = fs.readFileSync(path.join(__dirname, 'FilterReason.tsx'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } })
const exported = {}
vm.runInNewContext(compiled.outputText, { exports: exported, require: name => name === 'antd'
  ? { Button: 'button', Space: 'div', Typography: { Text: 'span', Paragraph: 'p' }, Modal: { info: value => calls.push(value) } }
  : require(name) })
const { FilterReason } = exported
for (const reason of [null, undefined, '', '   ']) {
  assert.equal(FilterReason({ reason }).props.children, '未记录过滤原因')
}
const reason = '命中规则「过滤：干扰项」：商品名称包含 [吸尘器, 麦克风]\n' + '很长的规则条件与原始值 '.repeat(100)
const children = FilterReason({ reason }).props.children
assert.equal(children[0].props.children, reason)
assert.equal(children[0].props.ellipsis.tooltip, reason)
assert.equal(calls.length, 0, 'only open the details when requested')
children[1].props.onClick()
assert.equal(calls.length, 1)
assert.equal(calls[0].title, '完整过滤原因')
assert.equal(calls[0].content.props.children, reason, 'dialog must preserve the full stored reason and line breaks')
assert.equal(calls[0].content.props.copyable, true)
const custom = FilterReason({ reason, title: '完整清洗原因', emptyText: '未记录清洗原因' })
custom.props.children[1].props.onClick()
assert.equal(calls[1].title, '完整清洗原因')
assert.equal(calls[1].content.props.children, reason)
assert.equal(FilterReason({ reason: null, emptyText: '未记录清洗原因' }).props.children, '未记录清洗原因')
