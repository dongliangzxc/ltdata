const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

// Exercise the real decision function with a controlled Modal boundary. No DOM
// or network is needed to verify that a warning requires an explicit choice.
const dialogs = []
const exportsObject = {}
const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, 'UploadWarnings.tsx'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
}).outputText
vm.runInNewContext(compiled, {
  exports: exportsObject,
  require(name) {
    if (name === 'antd') return { Modal: { confirm: options => dialogs.push(options) }, Typography: { Text: 'Text' } }
    if (name === 'react/jsx-runtime') return require(name)
    throw new Error(`Unexpected runtime dependency: ${name}`)
  },
})

const { reviewUploadWarnings } = exportsObject
const clean = { filename: 'clean.csv', issue_count: 0 }
const warning = { filename: 'warning.csv', issue_count: 3 }

;(async () => {
  assert.equal(await reviewUploadWarnings([]), true)
  assert.equal(await reviewUploadWarnings([clean]), true)
  assert.equal(dialogs.length, 0, 'Clean data must proceed without a confirmation dialog')

  let settled = false
  const cancel = reviewUploadWarnings([warning]).then(value => { settled = true; return value })
  await Promise.resolve()
  assert.equal(settled, false, 'Warnings must wait for an explicit user decision')
  assert.equal(dialogs.length, 1)
  dialogs[0].onCancel()
  assert.equal(await cancel, false, 'Returning to check must stop this upload attempt')

  const proceed = reviewUploadWarnings([warning])
  dialogs[1].onOk()
  assert.equal(await proceed, true, 'The user must be allowed to proceed despite warnings')

  const secondWarning = { filename: 'second.csv', issue_count: 1 }
  const batch = reviewUploadWarnings([clean, warning, secondWarning])
  assert.equal(dialogs.length, 3, 'A batch should show one combined decision')
  const reportedFiles = dialogs[2].content.props.reports.map(report => report.filename)
  assert.equal(reportedFiles.join(','), 'warning.csv,second.csv')
  dialogs[2].onCancel()
  assert.equal(await batch, false, 'Cancel applies to the whole batch')

  const retry = reviewUploadWarnings([clean])
  assert.equal(await retry, true, 'A previous cancellation must not block a clean retry')
  assert.equal(dialogs.length, 3)
  console.log('Upload warnings: clean, explicit confirmation, cancel, batch review and retry passed')
})().catch(error => { console.error(error); process.exitCode = 1 })
