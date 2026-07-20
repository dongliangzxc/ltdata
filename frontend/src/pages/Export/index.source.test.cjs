const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /useCategoryOptions/, 'export page should load category options')
assert.match(source, /const \[filters, setFilters\]/, 'export page should keep filter state')
assert.match(source, /listCleanJobs\(requestParams\)/, 'export page should reload jobs with filter params')
assert.match(source, /placeholder="全部品类"/, 'export page should render category filter')
assert.match(source, /placeholder="全部平台"/, 'export page should render platform filter')
assert.match(source, /placeholder="全部月份"/, 'export page should render month filter')
assert.match(source, /formatJobScope/, 'export page should show job scope details')
