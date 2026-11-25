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
new Function('require', 'exports', compiled)(() => ({
  listModels: async params => {
    calls.push(params)
    return { data: await response(params) }
  },
}), moduleUnderTest.exports)
const { compareModelOptions, loadAllModelOptions } = moduleUnderTest.exports

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
  console.log('model option sorting and pagination tests passed')
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
