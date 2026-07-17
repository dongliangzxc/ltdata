const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const sourcePath = path.join(__dirname, 'index.tsx')
assert.ok(fs.existsSync(sourcePath), 'data adjustment page file should exist')

const source = fs.readFileSync(sourcePath, 'utf8')

assert.match(source, /listCleanJobs/, 'data adjustment page should load clean jobs')
assert.match(source, /previewCleanJob/, 'data adjustment page should load selected clean job preview details')
assert.match(source, /useSearchParams/, 'data adjustment page should read and write clean_job_id query param')
assert.match(source, /cleanPreviewColumns/, 'data adjustment page should reuse shared clean preview columns')
assert.match(source, /数据调整/, 'data adjustment page should render the page title')
assert.match(source, /先选择清洗任务/, 'data adjustment page should show an empty state before a job is selected')
assert.match(source, /setSearchParams/, 'data adjustment page should update the URL when selecting a clean job')
