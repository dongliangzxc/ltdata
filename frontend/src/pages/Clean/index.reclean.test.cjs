const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const cleanSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')

assert.match(
  cleanSource,
  /force_reclean: action === 'recleaned'/,
  'Clean page should send force_reclean only for re-cleaning queued monthly rows',
)
assert.match(
  apiSource,
  /force_reclean\?: boolean/,
  'Monthly clean task payload should support force_reclean',
)
