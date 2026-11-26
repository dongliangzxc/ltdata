const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

const calls = []
let response
const source = fs.readFileSync(path.join(__dirname, 'utils/modelOptions.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const moduleUnderTest = { exports: {} }
const labelModule = { exports: {} }
new Function('exports', ts.transpileModule(fs.readFileSync(path.join(__dirname, '../../utils/modelLabel.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(labelModule.exports)
new Function('require', 'exports', compiled)(name => {
  if (name === '../../../utils/modelLabel') return labelModule.exports
  assert.equal(name, '../../../services/api')
  return {
    listModels: async params => {
      calls.push(params)
      return { data: await response(params) }
    },
  }
}, moduleUnderTest.exports)
const { compareModelOptions, loadAllModelOptions, buildModelSelectOptions, createModelOptionsLoader } = moduleUnderTest.exports

async function main() {
  const models = [
    { id: 1, brand_code: 'A', series: 'S10', model_code: 'A1' },
    { id: 2, brand_code: 'Z', series: ' S2 ', model_code: 'X10' },
    { id: 3, brand_code: 'B', series: '', model_code: 'K4' },
    { id: 4, brand_code: 'C', series: null, model_code: 'K2' },
    { id: 5, brand_code: 'D', series: '   ', model_code: 'K10' },
    { id: 6, brand_code: 'Y', series: 's2', model_code: 'X2' },
  ]
  assert.deepEqual([...models].sort(compareModelOptions).map(m => m.id), [4, 3, 5, 6, 2, 1],
    '按系列优先排序，无系列用型号；同系列按型号自然排序，品牌不应抢占排序优先级')
  const prepared = buildModelSelectOptions([
    { id: 1, brand_code: 'XDF', brand_name: '新东方', model_code: 'K10', model_name: '学习机' },
    { id: 2, brand_code: 'YH', brand_name: '永好', model_code: 'K2' },
  ])
  assert.deepEqual(prepared.map(option => option.value), [2, 1], '预处理的选项仍按系列/型号自然排序')
  const xdf = prepared.find(option => option.value === 1)
  assert.equal(xdf.label, '[XDF] K10')
  for (const keyword of ['xdf', '新东方', 'k10', '学习机']) {
    assert.ok(xdf.searchText.includes(keyword), `搜索索引应覆盖 ${keyword}`)
  }

  const firstPage = Array.from({ length: 2000 }, (_, id) => ({ id: id + 1 }))
  response = ({ page }) => ({ total: 2001, items: page === 1 ? firstPage : [{ id: 2001 }] })
  const result = await loadAllModelOptions('dictionary')
  assert.equal(result.length, 2001, '应加载全部选项，不能截断在 50 或 2000 条')
  assert.equal(result.at(-1).id, 2001)
  assert.deepEqual(calls.map(c => c.page), [1, 2])
  assert.ok(calls.every(c => c.category_code === 'dictionary' && c.exclude_placeholder === false))
  assert.ok(calls.every(c => !c.keyword), '打开和清空搜索均应可显示当前品类全部型号')

  calls.length = 0
  response = () => ({ total: 0, items: [] })
  assert.deepEqual(await loadAllModelOptions(), [])
  assert.equal(calls.length, 1, '空列表应结束分页')

  calls.length = 0
  response = ({ page }) => {
    if (page === 2) throw new Error('网络异常')
    return { total: 2001, items: firstPage }
  }
  await assert.rejects(loadAllModelOptions('dictionary'), /网络异常/,
    '分页失败应报告错误，避免将部分选项当作全部选项展示')

  calls.length = 0
  let clock = 0
  const loader = createModelOptionsLoader(() => clock)
  response = () => ({ total: 1, items: [{ id: 1 }] })
  const first = loader.load('dictionary')
  assert.equal(loader.load('dictionary'), first, '未完成的全量请求应复用，不能重复分页')
  const loaded = await first
  assert.equal(await loader.load('dictionary'), loaded, '重复展开应使用缓存数据')
  assert.equal(calls.length, 1)
  clock = 59_999
  await loader.load('dictionary')
  assert.equal(calls.length, 1)
  clock = 60_000
  await loader.load('dictionary')
  assert.equal(calls.length, 2, '过期后应重新加载，避免一直显示旧型号')
  await loader.load('tablet')
  assert.equal(calls.length, 3, '不同品类不能误用同一份缓存')
  assert.equal(calls.at(-1).category_code, 'tablet')
  loader.invalidate()
  await loader.load('dictionary')
  assert.equal(calls.length, 4, '新建型号后应清理缓存并重新获取')

  loader.invalidate()
  response = () => { throw new Error('加载失败') }
  await assert.rejects(loader.load('dictionary'), /加载失败/)
  response = () => ({ total: 1, items: [{ id: 2 }] })
  assert.deepEqual(await loader.load('dictionary'), [{ id: 2 }], '请求失败后应能重试')

  // 新建型号时可能仍有旧请求未返回，旧请求不能污染清理后的缓存。
  loader.invalidate()
  let releaseOld
  response = () => new Promise(resolve => { releaseOld = resolve })
  const oldRequest = loader.load('dictionary')
  loader.invalidate()
  response = () => ({ total: 1, items: [{ id: 3 }] })
  const latest = await loader.load('dictionary')
  releaseOld({ total: 1, items: [{ id: 2 }] })
  await oldRequest
  assert.equal(await loader.load('dictionary'), latest)
  assert.deepEqual(latest, [{ id: 3 }])
  console.log('model option sorting, pagination, search index and cache tests passed')
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
