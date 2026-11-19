const normalize = value => value.normalize('NFKC').toLowerCase().trim()

function searchableText(value) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(searchableText).join(' ')
  if (value && typeof value === 'object') return Object.values(value).map(searchableText).join(' ')
  return ''
}

/** Match every keyword, including synonyms and text inside tables and notes. */
export function searchSections(sections, query) {
  const terms = normalize(query).split(/\s+/).filter(Boolean)
  if (!terms.length) return sections
  return sections.filter(section => {
    const text = normalize(searchableText(section))
    return terms.every(term => text.includes(term))
  })
}

const tableCell = value => value.replace(/\|/g, '\\|').replace(/\n/g, '<br>')

/** The site, downloadable copy and repository manual share the same content. */
export function renderManualMarkdown(document) {
  const lines = [
    `# ${document.title}`, '',
    `> ${document.version} · 更新：${document.updatedAt} · 适用对象：${document.audience}`, '',
    document.intro, '',
    '## 目录', '',
    ...document.sections.map((section, index) => `${index + 1}. [${section.title}](#${section.id})`), '',
  ]
  for (const [index, section] of document.sections.entries()) {
    lines.push(`<a id="${section.id}"></a>`, '', `## ${String(index + 1).padStart(2, '0')} ${section.title}`, '', section.summary, '')
    if (section.entry) lines.push(`**入口**：${section.entry}`, '')
    for (const block of section.blocks) {
      switch (block.type) {
        case 'heading': lines.push(`### ${block.text}`, ''); break
        case 'paragraph': lines.push(block.text, ''); break
        case 'steps': lines.push(...block.items.map((item, i) => `${i + 1}. ${item}`), ''); break
        case 'list': lines.push(...block.items.map(item => `- ${item}`), ''); break
        case 'table':
          lines.push(`| ${block.headers.map(tableCell).join(' | ')} |`, `| ${block.headers.map(() => '---').join(' | ')} |`,
            ...block.rows.map(row => `| ${row.map(tableCell).join(' | ')} |`), '')
          break
        case 'note': lines.push(`> **${block.title}**`, '>', `> ${block.text}`, ''); break
        default: throw new Error(`Unknown manual block: ${block.type}`)
      }
    }
    lines.push('---', '')
  }
  return lines.join('\n')
}
