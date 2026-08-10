const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const sourcePath = path.join(__dirname, 'index.tsx');
const source = fs.readFileSync(sourcePath, 'utf8');
const {
  buildTransferFilterState,
  getDefaultTransferFilters,
  shouldClearTransferTarget,
} = require('./utils/transferFilters.cjs');

assert.doesNotMatch(source, /已匹配 \/ 已确认条目/, 'Match page should not display the reviewed/confirmed table card');
assert.doesNotMatch(source, /listReviewedMatches/, 'Match page should not request reviewed matches for a hidden table');
assert.doesNotMatch(source, /reviewedData/, 'Match page should not keep reviewed table data state');
assert.doesNotMatch(source, /reviewedColumns/, 'Match page should not keep reviewed table columns');

assert.match(source, /transferNotice/, 'Match page should track transfer notice state');
assert.match(source, /getTransferNotice/, 'Match page should call the transfer notice helper');
assert.match(source, /open=\{transferNoticeVisible\}/, 'Match page should render a Modal for transfer notices');
assert.match(source, /okText="刷新查看"/, 'transfer notice modal should make the refresh action prominent');
assert.match(source, /setInterval\(/, 'Match page should poll for transfer notices');
assert.match(source, /transferNoticeJobRef\.current !== requestJobId/, 'Match page should ignore stale transfer notice job responses');
assert.match(source, /transferNoticeSinceRef\.current !== requestSince/, 'Match page should ignore stale transfer notice baseline responses');
assert.match(source, /checked_at/, 'Match page should use the backend transfer notice checked_at cursor');
assert.match(source, /setTransferNoticeCheckedAt\(data\.checked_at\)/, 'Match page should store the server notice cursor from poll responses');
assert.match(source, /setTransferNoticeBaseline\(jobId, resp\.data\.checked_at\)/, 'Match page should initialize the transfer notice baseline from the server cursor');
assert.match(source, /const checkedAt = transferNoticeCheckedAtRef\.current/, 'Match page should acknowledge notices with the stored server cursor');
assert.doesNotMatch(source, /transferNoticeLatestAtRef/, 'Match page should not keep the old latest-transfer cursor ref');
assert.doesNotMatch(source, /new Date\(\)\.toISOString\(\)/, 'Match page should not use client time as a transfer notice cursor');
assert.match(source, /await Promise\.all\(/, 'Match page should await refresh work before clearing the transfer notice baseline');

assert.match(source, /transferCategoryFilter/, 'transfer modal should keep category filter state');
assert.match(source, /transferPlatformFilter/, 'transfer modal should keep platform filter state');
assert.match(source, /transferMonthFilter/, 'transfer modal should keep month filter state');
assert.match(source, /placeholder="品类"/, 'transfer modal should expose a category filter');
assert.match(source, /placeholder="平台"/, 'transfer modal should expose a platform filter');
assert.match(source, /placeholder="月度"/, 'transfer modal should expose a month filter');
assert.match(source, /buildTransferFilterState\(/, 'transfer modal should use shared filter behavior');
assert.match(source, /shouldClearTransferTarget\(/, 'transfer modal should clear hidden selected target through shared behavior');
assert.match(
  source,
  /getDefaultTransferFilters/,
  'transfer modal should derive default filters from the shared helper'
);
assert.match(
  source,
  /const defaultFilters = getDefaultTransferFilters\(selectedJob\)/,
  'transfer modal should default from the selected clean job'
);
assert.match(
  source,
  /setTransferCategoryFilter\(defaultFilters\.category\)/,
  'transfer modal should explicitly clear the category default'
);
assert.match(
  source,
  /setTransferPlatformFilter\(defaultFilters\.platform\)/,
  'transfer modal should default platform from the selected job'
);
assert.match(
  source,
  /setTransferMonthFilter\(defaultFilters\.month\)/,
  'transfer modal should default month from the selected job'
);
assert.match(
  source,
  /doSearchCleanTasks\('', defaultFilters\)/,
  'transfer modal initial search should use the freshly derived defaults'
);
assert.match(source, /category_code: filters\.category/, 'transfer modal search should send category filter to the API');
assert.match(source, /platform: filters\.platform/, 'transfer modal search should send platform filter to the API');
assert.match(source, /month: filters\.month/, 'transfer modal search should send month filter to the API');
assert.match(source, /seq !== transferSearchSeqRef\.current/, 'transfer modal search should ignore stale responses');

const transferTasks = [
  { id: 1, task_name: '运动相机 / jd / 202512', category_code: 'action_cameras', category_name: '运动相机', platform: 'jd', month: 202512, status: 'done', display_name: '运动相机 / jd / 202512' },
  { id: 2, task_name: '运动相机 / douyin / 202504', category_code: 'action_cameras', category_name: '运动相机', platform: 'douyin', month: 202504, status: 'done', display_name: '运动相机 / douyin / 202504' },
  { id: 3, task_name: '回音壁 / douyin / 202605', category_code: 'soundbar', category_name: '回音壁', platform: 'douyin', month: 202605, status: 'done', display_name: '回音壁 / douyin / 202605' },
];

const filteredState = buildTransferFilterState(
  transferTasks,
  { category: 'action_cameras', platform: 'jd', month: 202512 },
  new Map([['action_cameras', '运动相机'], ['soundbar', '回音壁']])
);
assert.deepEqual(filteredState.filteredOptions.map(item => item.id), [1], 'transfer filters should narrow target tasks by category/platform/month');
assert.deepEqual(filteredState.categoryOptions.map(item => item.value), ['soundbar', 'action_cameras'], 'transfer category options should be derived from candidate tasks');
assert.deepEqual(filteredState.platformOptions.map(item => item.value), ['douyin', 'jd'], 'transfer platform options should be derived from candidate tasks');
assert.match(source, /const TRANSFER_PLATFORM_OPTIONS/, 'transfer modal should define a complete platform option list');
assert.match(source, /value: 'tmall', label: '天猫'/, 'transfer modal platform options should include Tmall');
assert.match(source, /value: 'taobao', label: '淘宝'/, 'transfer modal platform options should include Taobao');
assert.match(source, /const categoryLabelMap = new Map\(categoryOptions\.map/, 'transfer modal category labels should use all categories, not permission-filtered categories');
const expandedOptionState = buildTransferFilterState(
  transferTasks,
  { category: 'projector' },
  new Map([['action_cameras', '运动相机']]),
  {
    categoryOptions: [{ value: 'projector', label: '投影仪' }],
    platformOptions: [{ value: 'tmall', label: '天猫' }, { value: 'taobao', label: '淘宝' }],
  }
);
assert.equal(expandedOptionState.categoryOptions.some(item => item.value === 'projector'), true, 'transfer category options should merge unrestricted category choices with task-derived categories');
assert.equal(expandedOptionState.categoryOptions.some(item => item.value === 'action_cameras'), true, 'transfer category options should keep task-derived categories');
assert.equal(expandedOptionState.platformOptions.some(item => item.value === 'tmall'), true, 'transfer platform options should include fixed platform choices even without current tasks');
assert.deepEqual(expandedOptionState.filteredOptions.map(item => item.id), [], 'external option choices should not bypass target task filtering');
assert.deepEqual(filteredState.monthOptions.map(item => item.value), [202605, 202512, 202504], 'transfer month options should sort newest first');

const allTaskFilterState = buildTransferFilterState(
  [
    ...transferTasks,
    { id: 51, category_code: 'projector', platform: 'jd', month: 202401 },
  ],
  {},
  new Map([['projector', '投影仪']])
);
assert.equal(allTaskFilterState.categoryOptions.some(item => item.value === 'projector'), true, 'transfer filter options should be derivable from the full task list, not only current search results');

assert.equal(shouldClearTransferTarget(2, filteredState.filteredOptions), true, 'selected target should clear when filters hide it');
assert.equal(shouldClearTransferTarget(1, filteredState.filteredOptions), false, 'selected target should remain when filters keep it visible');
assert.equal(shouldClearTransferTarget(undefined, filteredState.filteredOptions), false, 'empty selection should not be cleared again');

const defaultTransferFilters = getDefaultTransferFilters({
  id: 10,
  category_code: 'TV',
  platform: '京东',
  month: 202407,
});
assert.deepEqual(
  defaultTransferFilters,
  { category: undefined, platform: '京东', month: 202407 },
  'transfer defaults should use current platform and month without category'
);
assert.equal(
  Object.prototype.hasOwnProperty.call(defaultTransferFilters, 'category'),
  true,
  'transfer defaults should explicitly clear category'
);

const emptyTransferFilters = getDefaultTransferFilters({
  id: 11,
  category_code: 'TV',
  platform: null,
  month: null,
});
assert.deepEqual(
  emptyTransferFilters,
  { category: undefined, platform: undefined, month: undefined },
  'transfer defaults should tolerate missing platform and month'
);

const interventionRuleModalPath = path.join(__dirname, 'components', 'InterventionRuleModal.tsx');
const interventionRuleModalSource = fs.readFileSync(interventionRuleModalPath, 'utf8');

const detailTitleIndex = source.indexOf("title={activeTab === 'filtered' ? '干扰项详情' : '详情处理'}");
const productDetailIndex = source.indexOf('<Descriptions.Item label="商品名称" span={2}>{reviewDetail.item_name || \'-\'}</Descriptions.Item>');
const candidatesIndex = source.indexOf('<Card size="small" title="候选型号"');
const batchActionsIndex = source.indexOf('<SameTitleBatchActions');
const attributeInsightIndex = source.indexOf('<AttributeInsightCard detail={reviewDetail} onMetadataChanged={refreshCurrentReviewDetail} />');
const modelSearchPlaceholderIndex = source.indexOf('placeholder="搜索/选择其他型号确认"');
const createModelButtonIndex = source.indexOf('新建型号');
const modelSearchApiIndex = source.indexOf('const res = await listModels({');
const selectOtherModelIndex = source.indexOf('handleSelectOtherModel');
const systemSourceIndex = source.indexOf('<Descriptions.Item label="系统来源">{renderMatchSource(reviewDetail.match_source)}</Descriptions.Item>');
assert.equal(source.indexOf('<span>已匹配 / 已确认条目</span>'), -1, 'reviewed table title should not exist');
assert.equal(source.indexOf('buildMatchResultsColumns({'), -1, 'reviewed table columns should not exist');
assert.equal(source.indexOf('<ReselectModal'), -1, 'reviewed table reselect modal should not be mounted');
assert.equal(source.indexOf('重新选择'), -1, 'reviewed table reselect action should not be displayed');
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
assert.notEqual(modelSearchApiIndex, -1, 'model search should stay in the detail processing flow');
assert.notEqual(selectOtherModelIndex, -1, 'manual model selection should stay in the detail processing flow');

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

assert.notEqual(source.indexOf('isCandidateValidForBatch'), -1, '应存在 isCandidateValidForBatch 校验以禁用不可批量确认复选框');
assert.notEqual(source.indexOf('未识别品牌'), -1, '不可批量确认时应携带未识别品牌相关提示文案');
assert.equal(source.indexOf('候选型号码无效'), -1, '一键确认不应再因候选型号码无效禁用记录');

assert.notEqual(source.indexOf('batchConfirmMatch(selectedJobId'), -1, '批量确认接口应按 selectedJobId (clean_job_id) 路径调用');
assert.notEqual(source.indexOf('previewBatchConfirmMatch(selectedJobId'), -1, '批量预览接口应按 selectedJobId (clean_job_id) 路径调用');
assert.notEqual(source.indexOf('搜索并选择确认型号'), -1, '一键确认弹窗应要求选择确认型号');
assert.notEqual(source.indexOf('请选择确认型号'), -1, '未选择型号时应提示用户');
assert.notEqual(source.indexOf('已选当前页'), -1, '当前页批量选择计数应明确使用当前页口径');
assert.notEqual(source.indexOf('已选择全部搜索结果'), -1, '跨页全选计数应明确使用全部搜索结果口径');
assert.notEqual(source.indexOf('model_id: batchModelId'), -1, '批量确认 payload 应传递用户选择的 model_id');
assert.notEqual(source.indexOf("setCreateModelContext('batch')"), -1, '一键确认弹窗应支持新建型号并回填选择');

const viewMatchResultsButtonIndex = source.indexOf('查看本任务匹配结果')
assert.notEqual(viewMatchResultsButtonIndex, -1,
  'Match/index.tsx should have "查看本任务匹配结果" button')

assert.equal(source.indexOf("import { buildMatchResultsColumns } from '../MatchResults/columns'"), -1, 'Match page should not import reviewed table columns after hiding the table')
assert.equal(source.indexOf('buildMatchResultsColumns({'), -1, 'Match page should not build reviewed columns after hiding the table')
assert.equal(source.indexOf('const reviewedColumns = ['), -1, 'Match page should not keep a local reviewedColumns array')
