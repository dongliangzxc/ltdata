const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

// Exercise the real API interceptor: a confirm request that reaches the server
// without preflight must offer a choice and retry the same file after approval.
const source = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const report = { filename: 'warning.csv', issue_count: 7, affected_rows: 5 }
const payload = { temp_file_id: 'same-file', mapping: { price: 'price' }, ignore_columns: [], country_code: 'CN' }
async function scenario(decision, asJson = true, initiallyReviewed = false) {
  let intercept, resolveChoice
  const events = [], errors = []
  const choice = new Promise(resolve => { resolveChoice = resolve })
  class CanceledError extends Error { code = 'ERR_CANCELED' }
  const api = {
    interceptors: { request: { use() {} }, response: { use(ok, error) { intercept = error } } },
    request: async config => {
      events.push('retry')
      assert.equal(config._uploadQualityRetried, true)
      assert.deepEqual(JSON.parse(JSON.stringify(config.data)), { ...payload, quality_reviewed: true })
      return { data: { job_id: 42 } }
    },
  }
  vm.runInNewContext(compiled, {
    exports: {},
    require(name) {
      if (name === 'axios') return { default: { create: () => api, CanceledError } }
      if (name === 'antd') return { message: { error: value => errors.push(value) } }
      if (name === '../pages/Upload/UploadWarnings') return { reviewUploadWarnings: async reports => {
        events.push('choice')
        assert.equal(reports[0], report)
        return choice
      } }
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  const originalPayload = initiallyReviewed ? { ...payload, quality_reviewed: true } : payload
  const error = { response: { status: 409, data: { code: 'upload_quality_review_required', report } },
    config: { url: '/upload/confirm', data: asJson ? JSON.stringify(originalPayload) : originalPayload } }
  const pending = intercept(error).then(value => ({ value }), error => ({ error }))
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(events, ['choice'], 'Server warning must wait for user input')
  resolveChoice(decision)
  const result = await pending
  assert.deepEqual(errors, [], 'Quality warnings are a choice, not an error toast')
  if (decision) {
    assert.equal(result.value.data.job_id, 42)
    assert.deepEqual(events, ['choice', 'retry'])
  } else {
    assert.equal(result.error.code, 'ERR_CANCELED')
    assert.deepEqual(events, ['choice'], 'Cancel must not retry or consume the file')
  }
  const unrelated = { response: { status: 409, data: { detail: '另一个错误' } }, config: { url: '/upload/confirm' } }
  await assert.rejects(intercept(unrelated), e => e === unrelated)
  assert.deepEqual(errors, ['另一个错误'])
}
;(async () => {
  await scenario(true)
  await scenario(true, false)
  await scenario(false)
  await scenario(true, true, true)
  console.log('Server upload warnings: show real report, wait for choice, retry same payload on approval, cancel without error or import')
})().catch(error => { console.error(error); process.exitCode = 1 })
