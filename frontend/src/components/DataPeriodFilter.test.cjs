const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, 'DataPeriodFilter.tsx'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const exportsValue = {}
const jsx = (type, props) => ({ type, props })
vm.runInNewContext(compiled, { exports: exportsValue, require(name) {
  if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
  if (name === 'antd') return { Select: 'Select', Space: 'Space' }
  throw new Error(name)
} })
const calls = []
const onChange = (...args) => calls.push(args)
const render = options => exportsValue.default({ onChange, ...options }).props.children
const month = render({ value: 'month' })
assert.equal(month[1], false, 'monthly filters must not retain an invisible week selector')
month[0].props.onChange('week')
assert.deepEqual(calls.pop(), ['week', undefined])
const week = render({ value: 'week', week: 3 })
assert.deepEqual(Array.from(week[1].props.options, o => o.value), [1, 2, 3, 4, 5])
week[1].props.onChange(5)
assert.deepEqual(calls.pop(), ['week', 5])
week[1].props.onChange(undefined)
assert.deepEqual(calls.pop(), ['week', undefined])
week[0].props.onChange('month')
assert.deepEqual(calls.pop(), ['month', undefined], 'switching grain clears the previous week')
assert.equal(render({ value: 'week', upload: true })[1].props.placeholder, '从文件周列读取')
assert.equal(render({ value: 'week' })[1].props.placeholder, '全部周次')
const selections = []
const selected = render({ value: 'week', upload: true, hasWeekColumn: true, weeks: [1, 3], onWeeksChange: weeks => selections.push(Array.from(weeks)) })
assert.equal(selected[1].props.mode, 'multiple')
assert.deepEqual(Array.from(selected[1].props.value), [1, 3])
selected[1].props.onChange([5, 1])
assert.deepEqual(selections.pop(), [1, 5])
selected[1].props.onChange([])
assert.deepEqual(selections.pop(), [], 'clearing selection means all source weeks')
selected[0].props.onChange('month')
assert.deepEqual(selections.pop(), [], 'switching to monthly clears source filters')
assert.equal(render({ value: 'week', upload: true, hasWeekColumn: false })[1].props.mode, undefined, 'a file without weeks can only receive one manual week')
console.log('Period selection: month/week, weeks 1–5, clear, reset and upload source verified')
