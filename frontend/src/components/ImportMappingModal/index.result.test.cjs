const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /result\.specs_inserted/, 'import result should render model spec import count')
assert.match(source, /导入型号规格/, 'import result should label model spec import count')
