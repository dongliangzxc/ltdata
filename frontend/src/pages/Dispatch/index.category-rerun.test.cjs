const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const dispatchSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')

assert.match(
  apiSource,
  /export const runDispatch = \(fileId: number, categoryCode\?: string\)/,
  'runDispatch should accept an optional categoryCode argument',
)
assert.match(
  apiSource,
  /categoryCode \? \{ file_id: fileId, category_code: categoryCode \} : \{ file_id: fileId \}/,
  'runDispatch should only send category_code when provided',
)
assert.match(
  dispatchSource,
  /const \[runningCategoryKeys, setRunningCategoryKeys\] = useState<Set<string>>\(new Set\(\)\)/,
  'Dispatch detail modal should track category-level rerun loading state',
)
assert.match(
  dispatchSource,
  /const handleRunCategory = async \(category: DispatchCategoryStat\) =>/,
  'Dispatch page should define a category-level rerun handler',
)
assert.match(
  dispatchSource,
  /await runDispatch\(currentStatsBatch\.file_id, category\.category_code\)/,
  'category rerun should call runDispatch with the current file id and category code',
)
assert.match(
  dispatchSource,
  /title: '操作',[\s\S]*title="按品类分发"/,
  'category stats table should render an operation entry for category rerun',
)
assert.match(
  dispatchSource,
  /onConfirm=\{\(\) => handleRunCategory\(row\)\}/,
  'category stats table should confirm before running the selected category',
)
