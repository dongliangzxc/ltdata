const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const dispatchSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')

assert.match(
  apiSource,
  /downloaders: string\[\]/,
  'DispatchExportJob should include the deduplicated downloader name list',
)
assert.match(
  apiSource,
  /last_download_at: string \| null/,
  'DispatchExportJob should include the latest download timestamp for refresh tracking',
)
assert.match(
  dispatchSource,
  /title: '下载人'/,
  'Dispatch export jobs table should show a downloader column',
)
assert.doesNotMatch(
  dispatchSource,
  /title: '完成时间'/,
  'Dispatch export jobs table should no longer show the completion-time column',
)
assert.match(
  dispatchSource,
  /downloaders\.join\('、'\)/,
  'Downloader names should render as a readable deduplicated list',
)
