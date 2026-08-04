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
assert.match(
  apiSource,
  /export const downloadDispatchExport = \(token: string\) =>/,
  'Dispatch export API should expose an authenticated blob download helper',
)
assert.match(
  apiSource,
  /responseType: 'blob'/,
  'Dispatch export downloads should use blob responses so the bearer token is sent by axios',
)
assert.doesNotMatch(
  dispatchSource,
  /href=\{row\.download_url\}/,
  'Dispatch export download button should not rely on a bare href navigation',
)
assert.match(
  dispatchSource,
  /downloadDispatchExport\(/,
  'Dispatch export page should call the authenticated download helper',
)
assert.match(
  dispatchSource,
  /const downloadToken = row\.download_url\.slice\('\/api\/dispatch\/export\/download\/'.length\)/,
  'Dispatch export page should derive the row download token once',
)
assert.match(
  dispatchSource,
  /loading=\{downloadingToken === downloadToken\}/,
  'Dispatch export page should show row-level loading feedback while downloading',
)
assert.match(
  dispatchSource,
  /categoryPermissions\.length === 0\s*\?\s*categoryOptions\s*:\s*categoryOptions\.filter\(category => categoryPermissions\.includes\(category\.value\)\)/,
  'Dispatch visible categories should fall back to all categories when no category permissions are configured',
)
