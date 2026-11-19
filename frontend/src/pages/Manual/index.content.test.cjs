const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

;(async () => {
  const content = JSON.parse(fs.readFileSync(path.join(__dirname, 'content.json'), 'utf8'))
  const { searchSections, renderManualMarkdown } = await import(pathToFileURL(path.join(__dirname, 'manualTools.mjs')))
  const ids = new Set(content.sections.map(section => section.id))
  assert.equal(ids.size, content.sections.length, 'Duplicate chapter anchors would make navigation ambiguous')
  for (const link of content.quickLinks) assert(ids.has(link.target), `Broken quick link: ${link.target}`)
  for (const section of content.sections) {
    assert.match(section.id, /^[a-z][a-z0-9-]*$/)
    assert(section.title && section.summary && section.group)
    for (const block of section.blocks) {
      assert(['heading', 'paragraph', 'table', 'list', 'steps', 'note'].includes(block.type))
      if (block.type === 'table') {
        assert(block.headers.length > 0)
        for (const row of block.rows) assert.equal(row.length, block.headers.length, `Misaligned table in ${section.id}`)
      }
    }
  }

  assert.equal(searchSections(content.sections, '   '), content.sections)
  assert(searchSections(content.sections, '型号管理').some(section => section.id === 'models'), 'Old menu terminology must still find current instructions')
  assert(searchSections(content.sections, 'ＵＲＬ　去重').some(section => section.id === 'mappings'), 'Search must support width variants and multiple keywords')
  assert(searchSections(content.sections, '规格名称').some(section => section.id === 'metadata'), 'Fields inside tables must be searchable')
  assert(searchSections(content.sections, '409').some(section => section.id === 'faq'), 'Error codes must find troubleshooting')
  assert.deepEqual(searchSections(content.sections, '不存在的手册关键词xyz'), [])
  const original = JSON.stringify(content)
  searchSections(content.sections, '导入')
  assert.equal(JSON.stringify(content), original, 'Filtering must not remove chapters from the downloadable manual')

  const markdown = renderManualMarkdown(content)
  assert.equal(markdown, fs.readFileSync(path.resolve(__dirname, '../../../../docs/使用手册.md'), 'utf8'), 'Website/download and repository manual must be identical')
  for (const id of ids) assert(markdown.includes(`<a id="${id}"></a>`), `Missing document anchor: ${id}`)
  assert(!/luotu123|密码[：:]\s*`?(?:admin|luotu)/.test(markdown), 'The manual must not distribute a default password')
  const review = content.sections.find(section => section.id === 'review')
  const queueTable = review.blocks.find(block => block.type === 'table')
  assert.equal(queueTable.rows.length, 10, 'The current review screen has ten queues, including invalid and ignored')
  const menu = fs.readFileSync(path.resolve(__dirname, '../../components/Layout/index.tsx'), 'utf8')
  const titles = ['产品字段定义', '产品属性管理', '映射管理', '清洗任务', '数据分发', '匹配结果', '查询工作台', '数据导出']
  for (const title of titles) {
    assert(menu.includes(`label: '${title}'`), `Manual references a renamed menu: ${title}`)
    assert(markdown.includes(title), `Missing current menu: ${title}`)
  }
  const escaped = renderManualMarkdown({ ...content, sections: [{ ...content.sections[0], blocks: [{ type: 'table', headers: ['a', 'b'], rows: [['one|two', 'first\nsecond']] }] }] })
  assert(escaped.includes('one\\|two') && escaped.includes('first<br>second'), 'Downloaded tables must preserve delimiters and newlines')
  console.log('Manual navigation, search, current workflows and document consistency passed')
})().catch(error => { console.error(error); process.exitCode = 1 })
