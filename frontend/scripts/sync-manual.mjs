import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { renderManualMarkdown } from '../src/pages/Manual/manualTools.mjs'

const content = JSON.parse(readFileSync(new URL('../src/pages/Manual/content.json', import.meta.url), 'utf8'))
const output = new URL('../../docs/使用手册.md', import.meta.url)
const markdown = renderManualMarkdown(content)

if (process.argv.includes('--check')) {
  if (readFileSync(output, 'utf8') !== markdown) {
    throw new Error('使用手册与站内内容不一致，请运行 node frontend/scripts/sync-manual.mjs')
  }
  console.log('站内手册与文档内容一致')
} else {
  writeFileSync(output, markdown)
  console.log(`已同步 ${fileURLToPath(output)}`)
}
