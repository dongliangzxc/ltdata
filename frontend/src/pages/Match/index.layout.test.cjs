const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const sourcePath = path.join(__dirname, 'index.tsx');
const source = fs.readFileSync(sourcePath, 'utf8');
const interventionRuleModalPath = path.join(__dirname, 'components', 'InterventionRuleModal.tsx');
const interventionRuleModalSource = fs.readFileSync(interventionRuleModalPath, 'utf8');
const reselectModalPath = path.join(__dirname, 'components', 'ReselectModal.tsx');
const reselectModalSource = fs.readFileSync(reselectModalPath, 'utf8');

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
const sharedReviewedColumnsIndex = source.indexOf('buildMatchResultsColumns({');
const reselectModalUsageIndex = source.indexOf('<ReselectModal');
const reselectModalIndex = reselectModalSource.indexOf('title="重新选择型号"');
const reselectConfirmIndex = reselectModalSource.indexOf('okText="确认纠错"');
const reselectMappingHintIndex = reselectModalSource.indexOf('有可用 URL 线索时，纠错会同步覆盖对应 URL 映射');
const absoluteReselectMappingHintIndex = source.indexOf('纠错后会覆盖当前商品链接的 URL 映射');
const conditionalReselectSuccessIndex = reselectModalSource.indexOf('有可用 URL 线索时会同步更新 URL 映射');
const absoluteReselectSuccessIndex = source.indexOf('已完成型号纠错并同步 URL 映射');
const openReselectModalIndex = source.indexOf('openReselectModal');
const handleConfirmReselectIndex = reselectModalSource.indexOf('confirmMatch(detail.id');
const reselectRequestSeqRefIndex = reselectModalSource.indexOf('reselectRequestSeqRef');
const reselectStaleDetailGuardIndex = reselectModalSource.indexOf(
  'requestSeq !== reselectRequestSeqRef.current || d.id !== matchId'
);
const reselectCloseInvalidatesRequestIndex = reselectModalSource.indexOf('reselectRequestSeqRef.current += 1');
const reselectSearchRequestSeqRefIndex = reselectModalSource.indexOf('reselectSearchRequestSeqRef');
const reselectSearchStaleGuardIndex = reselectModalSource.indexOf('searchSeq !== reselectSearchRequestSeqRef.current');
const reselectSearchDetailGuardIndex = reselectModalSource.indexOf('reselectDetailRef.current?.id !== detailId');
const reselectSearchCategoryScopeIndex = reselectModalSource.indexOf('category_code: detail?.category_code || undefined');

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
assert.notEqual(source.indexOf('onReselect: openReselectModal'), -1, 'reviewed table should pass reselect action to shared columns');
assert.notEqual(reselectModalUsageIndex, -1, 'Match/index.tsx should mount <ReselectModal>');
assert.notEqual(reselectModalIndex, -1, 'reselect modal title should exist in ReselectModal.tsx');
assert.notEqual(reselectConfirmIndex, -1, 'reselect modal should use confirm correction copy in ReselectModal.tsx');
assert.notEqual(reselectMappingHintIndex, -1, 'reselect modal should mention URL mapping only when URL clues are available (in ReselectModal.tsx)');
assert.equal(absoluteReselectMappingHintIndex, -1, 'reselect modal should not claim URL mapping is always overwritten');
assert.notEqual(conditionalReselectSuccessIndex, -1, 'reselect success copy should mention URL mapping conditionally (in ReselectModal.tsx)');
assert.equal(absoluteReselectSuccessIndex, -1, 'reselect success copy should not claim URL mapping is always synchronized');
assert.notEqual(openReselectModalIndex, -1, 'reselect modal opener should exist');
assert.notEqual(handleConfirmReselectIndex, -1, 'reselect confirm handler should exist in ReselectModal.tsx');
assert.notEqual(reselectRequestSeqRefIndex, -1, 'reselect modal should track request sequence (in ReselectModal.tsx)');
assert.notEqual(reselectStaleDetailGuardIndex, -1, 'reselect modal should ignore stale detail responses (in ReselectModal.tsx)');
assert.notEqual(reselectCloseInvalidatesRequestIndex, -1, 'closing reselect modal should invalidate pending detail requests (in ReselectModal.tsx)');
assert.notEqual(reselectSearchRequestSeqRefIndex, -1, 'reselect model search should track request sequence (in ReselectModal.tsx)');
assert.notEqual(reselectSearchStaleGuardIndex, -1, 'reselect model search should ignore stale responses (in ReselectModal.tsx)');
assert.notEqual(reselectSearchDetailGuardIndex, -1, 'reselect model search should guard against detail changes (in ReselectModal.tsx)');
assert.notEqual(reselectSearchCategoryScopeIndex, -1, 'reselect model search should remain category-scoped (in ReselectModal.tsx)');
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
  sharedReviewedColumnsIndex !== -1 && sharedReviewedColumnsIndex < reselectModalUsageIndex,
  'reviewed table should build shared columns with reselect before rendering the reselect modal',
);

assert.notEqual(interventionRuleModalSource.indexOf("name=\"enable_reference_price\""), -1, "intervention edit form should expose the reference price toggle");
assert.notEqual(interventionRuleModalSource.indexOf("name=\"reference_price_op\""), -1, "intervention edit form should expose the price relation field");
assert.notEqual(interventionRuleModalSource.indexOf("name=\"reference_price_value\""), -1, "intervention edit form should expose the price value field");
assert.notEqual(interventionRuleModalSource.indexOf("conditions.reference_price"), -1, "intervention form should save reference price into rule conditions");
assert.notEqual(interventionRuleModalSource.indexOf("referencePriceToFormValues(rule.conditions)"), -1, "intervention edit should hydrate reference price fields from the selected rule");

// Task 7: 一键批量确认 —— 关键渲染 / 门控逻辑
const batchTabGateMarker = "activeTab === 'text_only' || activeTab === 'pending'";
const batchTabGateOccurrences = source.split(batchTabGateMarker).length - 1;
assert.ok(
  batchTabGateOccurrences >= 3,
  `批量确认按钮应至少在 3 处（复选框列 / 批量操作条 / 跨页提示条）被 text_only|pending Tab 门控，实际 ${batchTabGateOccurrences} 处`,
);

assert.notEqual(source.indexOf('isCandidateValidForBatch'), -1, '应存在 isCandidateValidForBatch 校验以禁用无效候选复选框');
assert.notEqual(source.indexOf('未识别品牌'), -1, '无效候选应携带未识别品牌相关提示文案');

assert.notEqual(source.indexOf('batchConfirmMatch(selectedJobId'), -1, '批量确认接口应按 selectedJobId (clean_job_id) 路径调用');
assert.notEqual(source.indexOf('previewBatchConfirmMatch(selectedJobId'), -1, '批量预览接口应按 selectedJobId (clean_job_id) 路径调用');

const viewMatchResultsButtonIndex = source.indexOf('查看本任务匹配结果')
assert.notEqual(viewMatchResultsButtonIndex, -1,
  'Match/index.tsx should have "查看本任务匹配结果" button')

assert.notEqual(source.indexOf("import { buildMatchResultsColumns } from '../MatchResults/columns'"), -1, 'Match page should import shared match result columns')
assert.notEqual(source.indexOf('buildMatchResultsColumns({'), -1, 'Match page should build reviewed columns from shared factory')
assert.equal(source.indexOf('const reviewedColumns = ['), -1, 'Match page should not keep a local reviewedColumns array')
