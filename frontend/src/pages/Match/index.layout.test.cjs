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
const modelSearchPlaceholderIndex = source.indexOf('placeholder="搜索/选择其他型号确认"');
const createModelButtonIndex = source.indexOf('新建型号');
const modelSearchApiIndex = source.indexOf('const res = await listModels({');
const selectOtherModelIndex = source.indexOf('handleSelectOtherModel');
const systemSourceIndex = source.indexOf('<Descriptions.Item label="系统来源">{renderMatchSource(reviewDetail.match_source)}</Descriptions.Item>');

assert.notEqual(detailTitleIndex, -1, '详情处理 card title should exist');
assert.notEqual(productDetailIndex, -1, 'review product detail block should exist');
assert.notEqual(candidatesIndex, -1, 'candidate model block should exist');
assert.notEqual(batchActionsIndex, -1, 'same title batch actions should exist');
assert.notEqual(attributeInsightIndex, -1, 'attribute insight block should exist');
assert.notEqual(modelSearchPlaceholderIndex, -1, 'current model area should include search/select control');
assert.notEqual(createModelButtonIndex, -1, 'current model area should include create model button');
assert.notEqual(modelSearchApiIndex, -1, 'model search should call listModels');
assert.notEqual(selectOtherModelIndex, -1, 'selecting another model should confirm the model');
assert.equal(systemSourceIndex, -1, 'review product detail should not show 系统来源');
assert.ok(
  detailTitleIndex < productDetailIndex
    && productDetailIndex < candidatesIndex
    && candidatesIndex < batchActionsIndex
    && batchActionsIndex < attributeInsightIndex,
  'review panel should render product detail, candidates, same case actions, then attributes',
);
assert.ok(
  productDetailIndex < modelSearchPlaceholderIndex && productDetailIndex < createModelButtonIndex,
  'search/select and create model controls should stay in the product detail block',
);
