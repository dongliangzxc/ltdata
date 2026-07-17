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
