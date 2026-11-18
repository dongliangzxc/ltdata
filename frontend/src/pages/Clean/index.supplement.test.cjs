const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, 'supplementFeedback.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } })
const exported = {}
vm.runInNewContext(compiled.outputText, { exports: exported })
const result = { inserted_rows: 100, duplicate_rows: 2 }
const queued = exported.supplementFeedback({ ...result, match_status: 'queued' })
assert.equal(queued.type, 'info')
assert.match(queued.message, /已加入清洗队列/)
assert.doesNotMatch(queued.message, /补充完成/)
assert.match(queued.message, /新增 100 条，重复跳过 2 条/)
assert.match(queued.description, /尚未完成/)
assert.match(queued.description, /失败后点击重试，无需重复上传/)
for (const match_status of ['done', undefined]) {
  const complete = exported.supplementFeedback({ ...result, match_status })
  assert.equal(complete.type, 'success')
  assert.match(complete.message, /补充完成/)
}
