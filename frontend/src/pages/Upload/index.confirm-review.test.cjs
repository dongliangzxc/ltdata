const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

// Execute the actual page handlers so both submission paths must carry the
// acknowledgement only after validation and the user's decision have finished.
const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const tree = ts.createSourceFile('index.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function handler(name, scope) {
  let initializer
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === name) initializer = node.initializer
    ts.forEachChild(node, visit)
  }
  visit(tree)
  assert(initializer, `Missing real page handler ${name}`)
  const js = ts.transpileModule(`exports.run = ${initializer.getText(tree)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText
  const exports = {}
  vm.runInNewContext(js, { exports, ...scope })
  return exports.run
}

const noop = () => {}
async function check(name, decision, validationFails = false) {
  const events = []
  let resolveReview
  const review = new Promise(resolve => { resolveReview = resolve })
  const payload = { temp_file_id: 'test-file', mapping: { price: 'price' }, ignore_columns: [] }
  const scope = {
    pollRef: { current: null }, confirming: false, allRequiredMapped: true,
    temp_file_id: payload.temp_file_id, mapping: payload.mapping, ignoreSet: new Set(),
    saveSwitch: false, saveName: '', selectedTemplateId: undefined, countryCode: 'CN', dataYear: 2026,
    batchConfirming: false,
    pendingFiles: [{ uid: 'test', filename: 'warning.csv', status: 'ready', countryCode: 'CN', headersResult: payload }],
    templates: [], filterRegion: undefined, filterYear: undefined,
    buildAutoMapping: () => ({ mapping: payload.mapping, ignoreColumns: [], missing: [] }),
    message: { warning: noop, loading: noop, destroy: noop, success: noop },
    setConfirming: noop, setUploadProgress: noop, setUploadError: noop, setCurrentJob: noop,
    setUploadProgressVisible: noop, setInterval: () => 1,
    setBatchItems: noop, setBatchConfirming: noop, setBatchModalOpen: noop, updateBatchItem: noop,
    setPendingFiles: noop, runFilesQuery: noop, refreshTemplates: noop, refreshUploadJobs: noop,
    waitForConfirmJob: async () => ({ ok: true, job: { status: 'done' } }),
    validateUpload: async () => {
      events.push('validate')
      if (validationFails) throw new Error('Scanner unavailable')
      return { data: { issue_count: 7 } }
    },
    reviewUploadWarnings: async () => { events.push('review'); return review },
    confirmUpload: async actual => {
      events.push('confirm')
      assert.equal(actual.quality_reviewed, true)
      assert.equal(actual.temp_file_id, payload.temp_file_id)
      return { data: { job_id: 1 } }
    },
  }
  const pending = handler(name, scope)()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(events, validationFails ? ['validate'] : ['validate', 'review'])
  resolveReview(decision)
  await pending
  assert.deepEqual(events, validationFails ? ['validate'] : decision ? ['validate', 'review', 'confirm'] : ['validate', 'review'])
}

;(async () => {
  for (const name of ['handleConfirm', 'handleBatchConfirm']) {
    await check(name, false)
    await check(name, true)
    await check(name, true, true)
  }
  console.log('Upload submission: single/batch wait for review, cancel and failed validation never submit, accepted submissions carry acknowledgement')
})().catch(error => { console.error(error); process.exitCode = 1 })
