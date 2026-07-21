const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /Tabs/, 'clean page should render tabs for active and deleted task lists')
assert.match(source, /已删除/, 'clean page should expose an archived/deleted task tab')
assert.match(source, /deleteCleanJob/, 'clean page should call the clean task delete API')
assert.match(source, /DeleteOutlined/, 'delete action should use the established delete icon')
assert.match(source, /Popconfirm/, 'delete action should require confirmation')
assert.match(source, /view === 'active'|view === "active"/, 'delete action should only be available in the active tab')
assert.match(source, /activeKey=\{jobView\}/, 'tabs should be controlled by the current clean job view')

assert.match(source, /navigate\(`\/data-adjustment\?clean_job_id=\$\{id\}`\)/, 'clean page should expose a separate data adjustment entry')
assert.match(source, /navigate\(`\/match\?job_id=\$\{id\}`\)/, 'clean page should preserve the match task entry')

assert.match(source, /previewCleanJob/, 'clean page should call previewCleanJob for task preview modal')
assert.match(source, /Modal/, 'clean page should render a preview modal')
assert.match(source, /setPreviewJobId\(id\)/, 'clean page preview action should select the preview job')
assert.match(source, /onAdjust: \(id: number\) => void/, 'clean page should model data adjustment as its own task action')
assert.match(source, /onClick=\{\(\) => onAdjust\(row\.id\)\}>数据调整/, 'data adjustment button should use the separate task action')
