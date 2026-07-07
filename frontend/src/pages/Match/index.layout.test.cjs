const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const sourcePath = path.join(__dirname, 'index.tsx');
const source = fs.readFileSync(sourcePath, 'utf8');

const detailTitleIndex = source.indexOf("title={activeTab === 'filtered' ? '干扰项详情' : '详情处理'}");
const productDetailIndex = source.indexOf('<Descriptions.Item label="商品名称" span={2}>{reviewDetail.item_name || \'-\'}</Descriptions.Item>');
const candidatesIndex = source.indexOf('<Card size="small" title="候选型号"');
const batchActionsIndex = source.indexOf('<SameTitleBatchActions');
const attributeInsightIndex = source.indexOf('<AttributeInsightCard detail={reviewDetail} />');
const systemSourceIndex = source.indexOf('<Descriptions.Item label="系统来源">{renderMatchSource(reviewDetail.match_source)}</Descriptions.Item>');

assert.notEqual(detailTitleIndex, -1, '详情处理 card title should exist');
assert.notEqual(productDetailIndex, -1, 'review product detail block should exist');
assert.notEqual(candidatesIndex, -1, 'candidate model block should exist');
assert.notEqual(batchActionsIndex, -1, 'same title batch actions should exist');
assert.notEqual(attributeInsightIndex, -1, 'attribute insight block should exist');
assert.equal(systemSourceIndex, -1, 'review product detail should not show 系统来源');
assert.ok(
  detailTitleIndex < productDetailIndex
    && productDetailIndex < candidatesIndex
    && candidatesIndex < batchActionsIndex
    && batchActionsIndex < attributeInsightIndex,
  'review panel should render product detail, candidates, same case actions, then attributes',
);
