const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

const permissionsColumnStart = source.indexOf("title: '目录权限'")
assert.notEqual(permissionsColumnStart, -1, 'users table should define a permissions column')
const permissionsColumn = source.slice(permissionsColumnStart, source.indexOf("title: '最后登录'", permissionsColumnStart))

assert.match(permissionsColumn, /width:\s*220/, 'permissions column should reserve enough width for permission tags')
assert.match(permissionsColumn, /display:\s*'flex'/, 'permission tags should render inside a constrained wrapping flex container')
assert.match(permissionsColumn, /flexWrap:\s*'wrap'/, 'permission tags should wrap within the permissions column')
assert.match(permissionsColumn, /maxWidth:\s*'100%'/, 'permission tag container should stay within the permissions cell')
assert.match(permissionsColumn, /marginInlineEnd:\s*0/, 'permission tags should not add extra Ant tag margin while wrapping')
assert.match(source, /scroll=\{\{\s*x:\s*1550\s*\}\}/, 'table horizontal scroll should cover the sum of fixed column widths')
assert.doesNotMatch(source, /fixed:\s*'right'/, 'actions column should not float over date or permission columns')
