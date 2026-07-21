const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const dir = __dirname
const sourcePath = path.join(dir, 'index.tsx')
const source = fs.existsSync(sourcePath) ? fs.readFileSync(sourcePath, 'utf8') : ''
const app = fs.readFileSync(path.join(dir, '../../App.tsx'), 'utf8')
const layout = fs.readFileSync(path.join(dir, '../../components/Layout/index.tsx'), 'utf8')
const perms = fs.readFileSync(path.join(dir, '../../auth/permissions.ts'), 'utf8')

assert.match(app, /path="\/data-adjustment"[\s\S]*<ProtectedPage><DataAdjustmentPage \/><\/ProtectedPage>/, 'data-adjustment route should mount DataAdjustmentPage')

const cleanIndex = layout.indexOf("key: '/clean'")
const adjustmentIndex = layout.indexOf("key: '/data-adjustment'")
const resultsIndex = layout.indexOf("key: '/match-results'")
assert.notEqual(cleanIndex, -1, 'workbench menu should include 清洗任务')
assert.notEqual(adjustmentIndex, -1, 'workbench menu should include 数据调整')
assert.notEqual(resultsIndex, -1, 'workbench menu should include 匹配结果')
assert.ok(cleanIndex < adjustmentIndex && adjustmentIndex < resultsIndex, '数据调整 should be between 清洗任务 and 匹配结果')
assert.match(layout, /pageTitles\.set\('\/data-adjustment', '数据调整'\)/, 'page title map should include 数据调整')
assert.match(perms, /\['\/data-adjustment', 'processing_workbench'\]/, 'permissions should include /data-adjustment')
assert.match(source, /export default function DataAdjustmentPage/, 'page shell should export DataAdjustmentPage')
assert.match(source, /WorkbenchPage/, 'page shell should reuse WorkbenchPage')
