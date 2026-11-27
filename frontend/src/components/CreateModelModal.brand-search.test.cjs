const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, 'CreateModelModal.tsx'), 'utf8')

assert.notEqual(source.indexOf('const loadBrands = async (keyword?: string)'), -1, 'brand loader should accept a search keyword')
assert.match(source, /loadAllBrandOptions\(keyword, isCurrent\)/, 'brand loader should fetch all matching pages with stale-request protection')
assert.notEqual(source.indexOf('onSearch={loadBrands}'), -1, 'brand Select should search brands remotely')
assert.notEqual(source.indexOf('filterOption={false}'), -1, 'brand Select should not rely on local filtering of a capped brand list')

let response
const calls = []
const loaderModule = { exports: {} }
const loaderSource = fs.readFileSync(path.join(__dirname, '../utils/brandOptions.ts'), 'utf8')
new Function('require', 'exports', ts.transpileModule(loaderSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(name => {
  assert.equal(name, '../services/api')
  return { listBrands: async params => {
    calls.push(params)
    return { data: await response(params) }
  } }
}, loaderModule.exports)
const { loadAllBrandOptions } = loaderModule.exports

async function main() {
  // One letter matches more than both the former 50-row cap and the API page cap.
  const brands = Array.from({ length: 2001 }, (_, index) => ({ brand_code: `B${index}` }))
  response = ({ page, page_size }) => ({
    total: brands.length,
    items: brands.slice((page - 1) * page_size, page * page_size),
  })
  assert.deepEqual(await loadAllBrandOptions(' b '), brands)
  assert.deepEqual(calls.map(call => call.page), [1, 2])
  assert.ok(calls.every(call => call.keyword === 'b' && call.page_size <= 2000))

  calls.length = 0
  response = () => ({ total: 0, items: [] })
  assert.deepEqual(await loadAllBrandOptions('   '), [])
  assert.equal(calls.length, 1)
  assert.equal(calls[0].keyword, undefined, 'clearing search should fetch all brands')

  response = ({ page }) => {
    if (page === 2) throw new Error('network failure')
    return { total: 2001, items: brands.slice(0, 2000) }
  }
  await assert.rejects(loadAllBrandOptions('b'), /network failure/,
    'a failed page must not leave a silently truncated result')

  // A slower initial/previous search must not replace the latest keyword results.
  calls.length = 0
  let releaseOld
  let currentSearch = 1
  response = () => new Promise(resolve => { releaseOld = resolve })
  const oldSearch = loadAllBrandOptions('b', () => currentSearch === 1)
  currentSearch = 2
  response = () => ({ total: 1, items: [{ brand_code: 'BOSE' }] })
  assert.deepEqual(await loadAllBrandOptions('bose', () => currentSearch === 2), [{ brand_code: 'BOSE' }])
  releaseOld({ total: 2001, items: brands.slice(0, 2000) })
  assert.equal(await oldSearch, undefined)
  assert.equal(calls.length, 2, 'superseded search should not request further pages')

  calls.length = 0
  let active = true
  response = () => new Promise(resolve => { releaseOld = resolve })
  const closedSearch = loadAllBrandOptions(undefined, () => active)
  active = false
  releaseOld({ total: 1, items: brands.slice(0, 1) })
  assert.equal(await closedSearch, undefined, 'closing the modal or creating a brand cancels pending results')

  console.log('CreateModelModal brand pagination, clearing, errors and stale-request tests passed')
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
