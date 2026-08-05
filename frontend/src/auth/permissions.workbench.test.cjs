const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const permissionsSource = fs.readFileSync(path.join(__dirname, 'permissions.ts'), 'utf8')
const layoutSource = fs.readFileSync(path.join(__dirname, '../components/Layout/index.tsx'), 'utf8')

assert.match(
  permissionsSource,
  /\['\/workbench', 'processing_workbench'\]/,
  'the /workbench route should use the processing workbench permission',
)

assert.match(
  layoutSource,
  /key: '\/workbench'[\s\S]*label: '查询工作台'/,
  'the workbench menu item should stay under the processing workbench section',
)
