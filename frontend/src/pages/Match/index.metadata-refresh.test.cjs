const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const sourcePath = path.join(__dirname, 'index.tsx')
const source = fs.readFileSync(sourcePath, 'utf8')

assert.match(source, /const refreshCurrentReviewDetail = async \(\) => \{/, 'Match page should define a metadata refresh callback')
assert.match(source, /if \(!selectedReviewId\) return/, 'refresh callback should guard missing selectedReviewId')
assert.match(source, /const res = await getMatchReviewDetail\(selectedReviewId\)/, 'refresh callback should reload current review detail')
assert.match(source, /setReviewDetail\(res\.data\)/, 'refresh callback should update reviewDetail')
assert.match(source, /<AttributeInsightCard detail=\{reviewDetail\} onMetadataChanged=\{refreshCurrentReviewDetail\} \/>/, 'AttributeInsightCard should receive the refresh callback')
