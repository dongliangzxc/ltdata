const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const helperSource = fs.readFileSync(path.join(__dirname, 'cleanProgress.ts'), 'utf8')
const compiled = ts.transpileModule(helperSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } })
const exported = {}
vm.runInNewContext(compiled.outputText, { exports: exported })
const { processingStatuses, mergeCleanProgress, finishedCleanJobIds, formatCleanProgress } = exported

assert.equal(processingStatuses.has('queued'), true)
assert.equal(processingStatuses.has('reviewing'), false)
const jobs = [
  { id: 1, status: 'queued', updated_at: '2026-11-17T12:00:02', row_out: 0 },
  { id: 2, status: 'matching', updated_at: '2026-11-17T12:00:00', row_out: 100 },
]
const stale = { id: 1, status: 'failed', updated_at: '2026-11-17T12:00:01', can_retry: true }
const current = { id: 2, status: 'reviewing', updated_at: '2026-11-17T12:00:03', progress_stage: '处理完成' }
const merged = mergeCleanProgress(jobs, [stale, current, { id: 999, status: 'failed' }])
assert.equal(merged.length, 2, 'responses from an old filter must not add tasks')
assert.equal(merged[0].status, 'queued', 'old failure must not overwrite a newly retried job')
assert.equal(merged[1].status, 'reviewing')
assert.equal(merged[1].row_out, 100, 'progress must retain task statistics')
assert.deepEqual([...finishedCleanJobIds(jobs, [stale, current])], [2])
assert.equal(formatCleanProgress({ status: 'cleaning', progress_stage: '清洗中', progress_processed: 12000, progress_total: 32946 }), '清洗中：12000 / 32946 条')
assert.equal(formatCleanProgress({ status: 'queued', progress_total: 0 }), '排队中')

const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
assert.match(page, /getCleanJobProgress\(progressIds\)/, 'poll a lightweight endpoint')
assert.match(page, /pollingInterval:.*3000 : 0/, 'only poll while tasks are active')
assert.match(page, /pollingWhenHidden: false/, 'pause progress polling on hidden pages')
assert.match(page, /retryCleanTask\(id\)/)
assert.match(page, /已加入清洗队列/, 'submission success must not claim processing is complete')
assert.match(page, /finishedCleanJobIds/, 'refresh full statistics after completion')
