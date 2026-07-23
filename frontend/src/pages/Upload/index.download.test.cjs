const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const pageSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')
const historyColumnsSource = pageSource.match(/const historyColumns = \([\s\S]*?\n\]/)?.[0] ?? ''

assert.match(apiSource, /export const downloadUploadFile = \(fileId: number\) =>/, 'API should export downloadUploadFile helper')
assert.match(apiSource, /api\.get\(`\/upload\/files\/\$\{fileId\}\/download`, \{ responseType: 'blob' \}\)/, 'downloadUploadFile should request blob response from upload download endpoint')
assert.match(pageSource, /DownloadOutlined/, 'Upload page should import a download icon')
assert.match(pageSource, /downloadUploadFile\(id\)/, 'Upload page should call downloadUploadFile with upload file id')
assert.match(pageSource, /URL\.createObjectURL/, 'Upload page should create an object URL for the downloaded blob')
assert.match(pageSource, /link\.download = filename/, 'Upload page should preserve original filename when downloading')
assert.match(pageSource, /message\.error\('下载失败，请稍后重试'\)/, 'Upload page should show a download failure message')
assert.match(historyColumnsSource, /下载/, 'Upload history operation column should render a download action')
assert.match(historyColumnsSource, /onDownload\(row\.id, row\.filename\)/, 'Download action should pass row id and filename')
