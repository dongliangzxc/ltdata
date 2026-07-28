const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const sourcePath = path.join(__dirname, 'AttributeInsightCard.tsx');
const source = fs.readFileSync(sourcePath, 'utf8');

assert.match(source, /title="品类属性"/, 'attribute card should be titled category attributes');
assert.match(source, /品类字段要求/, 'attribute card should render category field requirements');
assert.match(source, /搜索字段要求/, 'attribute card should expose a search input');
assert.match(source, /新建字段要求/, 'attribute card should expose a create-field action');
assert.match(source, /metadataSpecs/, 'attribute card should read metadata specs from detail data');
assert.match(source, /modelSpecs/, 'attribute card should still render model specs');
assert.match(source, /matchAttrs/, 'attribute card should still render automatic attributes');
assert.match(source, /onMetadataChanged/, 'attribute card should accept a refresh callback');
assert.match(source, /createMetadata/, 'attribute card should create metadata records');
assert.match(source, /metadataModalOpen/, 'attribute card should manage a creation modal');
assert.doesNotMatch(source, /CreateModelModal/, 'attribute card should not depend on the create-model modal');
