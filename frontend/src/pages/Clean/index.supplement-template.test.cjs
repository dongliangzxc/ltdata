const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')
const modal = page.slice(page.indexOf('title={supplementJob'), page.indexOf('{supplementResult &&'))
assert.match(modal, /onClick=\{handleDownloadSupplementTemplate\}/)
assert.match(modal, /下载示例/)
assert.match(modal, /loading=\{downloadingSupplementTemplate\}/)
assert.match(modal, /替换示例数据、保留表头后即可上传/)
assert.ok(modal.indexOf('下载示例') < modal.indexOf('<Upload.Dragger'), 'sample should be visible before picking a file')

const apiExports = {}
const apiCalls = []
const apiHelper = apiSource.slice(apiSource.indexOf('export const downloadSupplementTemplate'), apiSource.indexOf('export interface SupplementCleanTaskResult'))
vm.runInNewContext(ts.transpileModule(apiHelper, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
  exports: apiExports, api: { get: (...args) => { apiCalls.push(args); return Promise.resolve() } },
})
apiExports.downloadSupplementTemplate()
assert.deepEqual(JSON.parse(JSON.stringify(apiCalls)), [['/clean/supplement-template', { responseType: 'blob' }]])

const handlerSource = page.slice(page.indexOf('const handleDownloadSupplementTemplate ='), page.indexOf('const handleSupplement ='))
const compiled = ts.transpileModule(`${handlerSource}\nexports.download = handleDownloadSupplementTemplate`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

async function testDownload(fail) {
  const exported = {}
  const loading = []
  const events = []
  const blob = new Blob(['sample workbook'])
  const link = { click: () => events.push('click'), remove: () => events.push('remove') }
  vm.runInNewContext(compiled, {
    exports: exported,
    setDownloadingSupplementTemplate: value => loading.push(value),
    downloadSupplementTemplate: async () => {
      if (fail) throw new Error('network error')
      return { data: blob }
    },
    URL: {
      createObjectURL: data => { assert.equal(data, blob); return 'blob:example' },
      revokeObjectURL: url => { assert.equal(url, 'blob:example'); events.push('revoke') },
    },
    document: {
      createElement: tag => { assert.equal(tag, 'a'); return link },
      body: { appendChild: element => { assert.equal(element, link); events.push('append') } },
    },
  })
  await exported.download()
  assert.deepEqual(loading, [true, false], 'success and failure must both allow another download')
  if (fail) {
    assert.deepEqual(events, [])
  } else {
    assert.equal(link.href, 'blob:example')
    assert.equal(link.download, '补充数据上传示例.xlsx')
    assert.deepEqual(events, ['append', 'click', 'remove', 'revoke'])
  }
}
Promise.all([testDownload(false), testDownload(true)]).catch(error => { console.error(error); process.exitCode = 1 })
