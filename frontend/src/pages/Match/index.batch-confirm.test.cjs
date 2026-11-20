const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
assert.match(source, /okText="确认并更新映射"/, 'confirmation should clearly name the mapping update')
assert.match(source, /已有的商品链接映射也会按所选型号更新/, 'users should see that their selection replaces an existing link mapping')
assert.match(source, /其他任务中已有的确认结果不会自动修改/, 'the dialog should explain which existing results remain independent')
