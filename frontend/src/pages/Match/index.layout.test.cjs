const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const sourcePath = path.join(__dirname, 'index.tsx');
const source = fs.readFileSync(sourcePath, 'utf8');
const interventionRuleModalPath = path.join(__dirname, 'components', 'InterventionRuleModal.tsx');
const interventionRuleModalSource = fs.readFileSync(interventionRuleModalPath, 'utf8');

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
const reviewedTableTitleIndex = source.indexOf('<span>已匹配 / 已确认条目</span>');
const reselectButtonIndex = source.indexOf('重新选择');
const reselectModalIndex = source.indexOf('title="重新选择型号"');
const reselectConfirmIndex = source.indexOf('okText="确认纠错"');
const reselectMappingHintIndex = source.indexOf('有可用 URL 线索时，纠错会同步覆盖对应 URL 映射');
const absoluteReselectMappingHintIndex = source.indexOf('纠错后会覆盖当前商品链接的 URL 映射');
const conditionalReselectSuccessIndex = source.indexOf('有可用 URL 线索时会同步更新 URL 映射');
const absoluteReselectSuccessIndex = source.indexOf('已完成型号纠错并同步 URL 映射');
const openReselectModalIndex = source.indexOf('openReselectModal');
const handleConfirmReselectIndex = source.indexOf('handleConfirmReselect');
const reselectRequestSeqRefIndex = source.indexOf('reselectRequestSeqRef');
const reselectStaleDetailGuardIndex = source.indexOf('requestSeq !== reselectRequestSeqRef.current || detail.id !== row.id');
const reselectCloseInvalidatesRequestIndex = source.indexOf('reselectRequestSeqRef.current += 1');
const reselectSearchRequestSeqRefIndex = source.indexOf('reselectSearchRequestSeqRef');
const reselectSearchStaleGuardIndex = source.indexOf('searchSeq !== reselectSearchRequestSeqRef.current');
const reselectSearchDetailGuardIndex = source.indexOf('reselectDetailRef.current?.id !== detailId');
const reselectSearchCategoryScopeIndex = source.indexOf('category_code: reselectDetail?.category_code || undefined');

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
assert.notEqual(reviewedTableTitleIndex, -1, 'reviewed table title should exist');
assert.notEqual(reselectButtonIndex, -1, 'reviewed table should include a reselect action');
assert.notEqual(reselectModalIndex, -1, 'reselect modal should exist');
assert.notEqual(reselectConfirmIndex, -1, 'reselect modal should use confirm correction copy');
assert.notEqual(reselectMappingHintIndex, -1, 'reselect modal should mention URL mapping only when URL clues are available');
assert.equal(absoluteReselectMappingHintIndex, -1, 'reselect modal should not claim URL mapping is always overwritten');
assert.notEqual(conditionalReselectSuccessIndex, -1, 'reselect success copy should mention URL mapping conditionally');
assert.equal(absoluteReselectSuccessIndex, -1, 'reselect success copy should not claim URL mapping is always synchronized');
assert.notEqual(openReselectModalIndex, -1, 'reselect modal opener should exist');
assert.notEqual(handleConfirmReselectIndex, -1, 'reselect confirm handler should exist');
assert.notEqual(reselectRequestSeqRefIndex, -1, 'reselect modal should track request sequence');
assert.notEqual(reselectStaleDetailGuardIndex, -1, 'reselect modal should ignore stale detail responses');
assert.notEqual(reselectCloseInvalidatesRequestIndex, -1, 'closing reselect modal should invalidate pending detail requests');
assert.notEqual(reselectSearchRequestSeqRefIndex, -1, 'reselect model search should track request sequence');
assert.notEqual(reselectSearchStaleGuardIndex, -1, 'reselect model search should ignore stale responses');
assert.notEqual(reselectSearchDetailGuardIndex, -1, 'reselect model search should guard against detail changes');
assert.notEqual(reselectSearchCategoryScopeIndex, -1, 'reselect model search should remain category-scoped');
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
assert.ok(
  reviewedTableTitleIndex < reselectButtonIndex && reselectButtonIndex < reselectModalIndex,
  'reviewed table should expose reselect before rendering the reselect modal',
);

assert.notEqual(interventionRuleModalSource.indexOf("name=\"enable_reference_price\""), -1, "intervention edit form should expose the reference price toggle");
assert.notEqual(interventionRuleModalSource.indexOf("name=\"reference_price_op\""), -1, "intervention edit form should expose the price relation field");
assert.notEqual(interventionRuleModalSource.indexOf("name=\"reference_price_value\""), -1, "intervention edit form should expose the price value field");
assert.notEqual(interventionRuleModalSource.indexOf("conditions.reference_price"), -1, "intervention form should save reference price into rule conditions");
assert.notEqual(interventionRuleModalSource.indexOf("referencePriceToFormValues(rule.conditions)"), -1, "intervention edit should hydrate reference price fields from the selected rule");
