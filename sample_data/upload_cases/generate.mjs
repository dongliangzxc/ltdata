// Run with the bundled Node runtime and @oai/artifact-tool on the module path.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = path.dirname(fileURLToPath(import.meta.url));
const standard = ['platform', 'month', 'item_id', 'item_name', 'sales_qty', 'sales_amount', 'price'];
const identity = Object.fromEntries(standard.map(key => [key, key]));
const cases = [];
const row = (id, changes = {}) => ({
  platform: 'jd', month: 202610, item_id: `UPLOAD-TEST-${id}`,
  item_name: `上传测试商品 ${id}`, sales_qty: 10, sales_amount: 990, price: 99,
  ...changes,
});
const matrix = (rows, fields = standard) => rows.map(item => fields.map(key => item[key] ?? null));
const csv = (headers, values) => [headers, ...values].map(values => values.map(value => {
  const text = value == null ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}).join(',')).join('\r\n') + '\r\n';

async function addCsv(file, rows, options = {}) {
  const fields = options.fields ?? standard;
  const headers = options.headers ?? fields;
  const values = matrix(rows, fields);
  const content = csv(headers, values);
  let bytes = Buffer.from(`\ufeff${content}`);
  if (options.encoding === 'gbk') {
    bytes = execFileSync(process.env.UPLOAD_FIXTURE_PYTHON ?? 'python3',
      ['-c', 'import sys; sys.stdout.buffer.write(sys.stdin.read().encode("gbk"))'], { input: content });
  }
  await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
  await fs.writeFile(path.join(root, file), bytes);
  cases.push({ file, rows: rows.length, mapping: options.mapping ?? identity,
    ignore_columns: options.ignore_columns ?? [], ...options.expected });
}

async function addXlsx(file, sheets, mapping, expected = {}) {
  const workbook = Workbook.create();
  for (const spec of sheets) {
    const sheet = workbook.worksheets.add(spec.name ?? '上传数据');
    const values = [spec.headers, ...spec.values];
    const area = sheet.getRangeByIndexes(0, 0, values.length, spec.headers.length);
    area.values = values;
    area.format.font = { name: 'Arial', size: 10 };
    area.format.columnWidth = 20;
    area.format.rowHeight = 25;
    area.format.verticalAlignment = 'center';
    sheet.showGridLines = false;
    const header = sheet.getRangeByIndexes(0, 0, 1, spec.headers.length);
    header.format.fill = '#243B53';
    header.format.font = { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' };
    header.format.wrapText = true;
    header.format.horizontalAlignment = 'center';
    header.format.rowHeight = 44;
    for (let index = 0; index < spec.headers.length; index++) {
      const label = spec.headers[index];
      const column = sheet.getRangeByIndexes(0, index, values.length, 1);
      if (/名称|标题/.test(label)) column.format.columnWidth = 35;
      if (/ID|ASIN|item_id/.test(label)) {
        column.setNumberFormat('@');
        column.format.columnWidth = 30;
      }
    }
    if (values.length > 10) sheet.freezePanes.freezeRows(1);
  }
  workbook.recalculate();
  // These are raw import fixtures: row 1 must remain the header, with no cover or totals.
  const overview = await workbook.inspect({ kind: 'sheet', include: 'id,name', maxChars: 1000 });
  console.log(file, overview.ndjson);
  await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(root, file));
  await fs.rm(path.join(root, `${file}.inspect.ndjson`), { force: true });
  await fs.mkdir(path.join(root, '.previews'), { recursive: true });
  for (let index = 0; index < sheets.length; index++) {
    const preview = await workbook.render({ sheetName: sheets[index].name ?? '上传数据',
      range: `A1:${String.fromCharCode(64 + sheets[index].headers.length)}${Math.min(sheets[index].values.length + 1, 6)}`,
      scale: 1, format: 'png' });
    await fs.writeFile(path.join(root, '.previews', `${path.basename(file)}-${index}.png`),
      new Uint8Array(await preview.arrayBuffer()));
  }
  cases.push({ file, rows: sheets[0].values.length, mapping, ignore_columns: [], ...expected });
}

const cnHeaders = ['平台', '月', '宝贝ID', '宝贝名称', '销量', '销售额', '价格'];
const cnMapping = Object.fromEntries(cnHeaders.map((name, index) => [name, standard[index]]));
await addXlsx('normal/jd.xlsx', [{ headers: cnHeaders,
  values: matrix([row('JD-001'), row('JD-002'), row('JD-003', { sales_qty: 0, sales_amount: 0, price: 0 })]) }], cnMapping, { inserted: 3 });
await addCsv('normal/tmall_utf8.csv', [row('TM-001', { platform: '天猫' }), row('TM-002', { platform: 'tmall' })],
  { headers: cnHeaders, mapping: cnMapping, expected: { inserted: 2 } });
await addCsv('normal/taobao_gbk.csv', [row('TB-001', { platform: '淘宝' }), row('TB-002', { platform: 'taobao' })],
  { headers: cnHeaders, mapping: cnMapping, encoding: 'gbk', expected: { inserted: 2 } });
const overseasFields = ['item_id', 'item_name', 'sales_qty', 'sales_amount', 'price'];
const overseasHeaders = ['ASIN', '产品名称', '销量', '销额', '价格'];
await addXlsx('normal/202610_amazon_US_filename.xlsx', [{ headers: overseasHeaders,
  values: matrix([row('US-001', { price: 39.99, sales_amount: 399.9 }), row('US-002')], overseasFields) }],
  Object.fromEntries(overseasHeaders.map((name, index) => [name, overseasFields[index]])), { inserted: 2, country_code: 'US' });
await addCsv('normal/shopee.csv', [row('SG-001', { platform: '虾皮' }), row('SG-002', { platform: 'shopee' })],
  { expected: { inserted: 2, country_code: 'SG' } });
const customHeaders = ['渠道', '统计月份', '商品编号', '商品标题', '售出件数', '成交金额', '成交单价', '颜色', '内部备注'];
await addCsv('normal/custom_columns.csv', [row('EXT-001', { color: '蓝色', note: '忽略本列' }), row('EXT-002', { color: '白色' })],
  { fields: [...standard, 'color', 'note'], headers: customHeaders,
    mapping: { ...Object.fromEntries(customHeaders.slice(0, 7).map((name, index) => [name, standard[index]])), 颜色: '__ext__' },
    ignore_columns: ['内部备注'], expected: { inserted: 2 } });
await addCsv('normal/quoted_multiline.csv', [row('TEXT-001', { item_name: '测试标题, 含"引号"\n第二行' }),
  row('LONG-ID', { item_id: '000001234567890123456789', sales_qty: 0, sales_amount: 0, price: 0 })], { expected: { inserted: 2 } });
await addCsv('dedup/in_file.csv', [row('DUP-A'), row('DUP-A'), row('DUP-B'), row('DUP-A', { month: 202611 })],
  { expected: { inserted: 3, skipped: 1 } });
const chunkRows = Array.from({ length: 5000 }, (_, index) => row(`CHUNK-${String(index).padStart(5, '0')}`));
await addCsv('dedup/cross_chunk_5002.csv', [...chunkRows, chunkRows[0], row('CHUNK-05000')],
  { expected: { inserted: 5001, skipped: 1 } });
await addCsv('dedup/reimport_a.csv', [row('RE-A'), row('RE-B')], { expected: { inserted: 2 } });
await addCsv('dedup/reimport_b.csv', [row('RE-B'), row('RE-C')], { expected: { inserted: 1, skipped: 1, after: 'dedup/reimport_a.csv' } });
await addCsv('same_name/a/data.csv', [row('SAME-A')], { expected: { inserted: 1 } });
await addCsv('same_name/b/data.csv', [row('SAME-B')], { expected: { inserted: 1, preserves_originals: true } });
await addCsv('invalid/missing_price.csv', [row('MISSING-COL')],
  { fields: standard.filter(key => key !== 'price'), mapping: Object.fromEntries(standard.filter(key => key !== 'price').map(key => [key, key])),
    expected: { confirm_status: 422 } });
await addCsv('invalid/missing_values.csv', [row('BLANK-ID', { item_id: null }), row('BLANK-NAME', { item_name: null }), row('BLANK-PRICE', { price: null })],
  { expected: { warnings_expected: 3, job_status: 'done' } });
await addCsv('invalid/bad_numbers.csv', [row('NUM-001', { sales_amount: '1,299.00', price: '￥99.00' }), row('NUM-002', { sales_qty: '未知' })],
  { expected: { warnings_expected: 3, job_status: 'done' } });
await addCsv('invalid/fractional_qty.csv', [row('FRACTION', { sales_qty: 1.5 })], { expected: { warnings_expected: 1, job_status: 'done' } });
await addCsv('invalid/invalid_month.csv', [row('MONTH-001', { month: 202613 }), row('MONTH-002', { month: 202600 })],
  { expected: { warnings_expected: 2, job_status: 'done' } });
await addXlsx('invalid/empty.xlsx', [{ headers: standard, values: [] }], identity, { known_issue: '空表被标记成功' });
await addCsv('invalid/duplicate_target.csv', [row('DOUBLE-QTY', { second_qty: 20 })],
  { fields: [...standard, 'second_qty'], mapping: { ...identity, second_qty: 'sales_qty' },
    expected: { known_issue: '重复映射未在提交阶段拦截' } });
await fs.writeFile(path.join(root, 'invalid/corrupt.xlsx'), 'This is intentionally not an Excel workbook.');
cases.push({ file: 'invalid/corrupt.xlsx', headers_status: 422 });
await addCsv('invalid/uppercase.CSV', [row('UPPER')], { expected: { known_issue: '大写扩展名被拒绝' } });
await addCsv('filename_conflict/202611_amazon_US_conflict.csv', [row('CONFLICT', { platform: 'shopee', month: 202610 })],
  { expected: { country_code: 'US', known_issue: '文件名覆盖表内月份及平台且无冲突提示' } });
await addXlsx('invalid/multiple_sheets.xlsx', [
  { name: '第一张数据', headers: standard, values: matrix([row('SHEET-1')]) },
  { name: '第二张数据', headers: standard, values: matrix([row('SHEET-2')]) },
], identity, { inserted: 1, limitation: '目前只读取一个工作表，第二张不入库' });
await fs.writeFile(path.join(root, 'manifest.json'), JSON.stringify({ synthetic: true, cases }, null, 2) + '\n');
console.log(`Generated ${cases.length} upload fixtures.`);
