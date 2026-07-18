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

assert.doesNotMatch(source, /navigate\(`\/data-adjustment/, 'clean page preview action should not navigate to data adjustment')

assert.match(source, /previewCleanJob/, 'clean page should call previewCleanJob for task preview modal')
assert.match(source, /Modal/, 'clean page should render a preview modal')
assert.match(source, /setPreviewJobId\(id\)/, 'clean page preview action should select the preview job')
assert.doesNotMatch(source, /\/data-adjustment\?clean_job_id=/, 'clean page should not navigate task preview to data adjustment')
