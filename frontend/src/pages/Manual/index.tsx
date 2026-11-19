import { useMemo, useState } from 'react'
import { Alert, Button, Empty, Input, Select, Typography } from 'antd'
import { ArrowDownOutlined, DownloadOutlined, PrinterOutlined, SearchOutlined } from '@ant-design/icons'
import content from './content.json'
import { renderManualMarkdown, searchSections } from './manualTools.mjs'
import type { ManualBlock, ManualDocument } from './types'
import './manual.css'

const manual = content as ManualDocument
const { Title, Paragraph } = Typography

function Block({ block }: { block: ManualBlock }) {
  switch (block.type) {
    case 'paragraph': return <p>{block.text}</p>
    case 'heading': return <h3>{block.text}</h3>
    case 'steps': return <ol className="manual-steps">{block.items.map((item, i) => <li key={i}>{item}</li>)}</ol>
    case 'list': return <ul className="manual-list">{block.items.map((item, i) => <li key={i}>{item}</li>)}</ul>
    case 'table': return (
      <div className="manual-table-scroll" tabIndex={0} role="region" aria-label={block.headers.join('、')}>
        <table>
          <thead><tr>{block.headers.map(header => <th scope="col" key={header}>{header}</th>)}</tr></thead>
          <tbody>{block.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
        </table>
      </div>
    )
    case 'note': return (
      <Alert type={block.tone} showIcon message={block.title} description={block.text} className="manual-note" />
    )
  }
}

function downloadManual() {
  const url = URL.createObjectURL(new Blob([renderManualMarkdown(manual)], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `洛图数据平台使用手册_${manual.updatedAt}.md`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ManualPage() {
  const [query, setQuery] = useState('')
  const sections = useMemo(() => searchSections(manual.sections, query), [query])
  const groups = [...new Set(sections.map(section => section.group))]

  return (
    <div className="manual-page" id="manual-top">
      <header className="manual-cover">
        <div className="manual-edition">使用指南 <span>/</span> {manual.version}</div>
        <Title level={2}>把一批数据，处理清楚。</Title>
        <Paragraph>{manual.intro}</Paragraph>
        <div className="manual-cover-footer">
          <span>更新于 {manual.updatedAt} · {manual.audience}</span>
          <div className="manual-actions">
            <Button icon={<DownloadOutlined />} onClick={downloadManual}>下载完整手册</Button>
            <Button icon={<PrinterOutlined />} onClick={() => window.print()}>打印当前内容</Button>
          </div>
        </div>
      </header>

      <div className="manual-quick-links" aria-label="常用操作指南">
        {manual.quickLinks.map((link, index) => (
          <a key={link.target} href={`#${link.target}`} onClick={() => setQuery('')}>
            <span className="manual-quick-number">0{index + 1}</span>
            <span><strong>{link.title}</strong><small>{link.description}</small></span>
            <ArrowDownOutlined />
          </a>
        ))}
      </div>

      <div className="manual-search-bar">
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索步骤、字段或问题，如：产品系列、补充数据、去重"
          aria-label="搜索使用手册"
          value={query}
          onChange={event => setQuery(event.target.value)}
          allowClear
          size="large"
        />
        <span role="status" aria-live="polite">{query.trim() ? `找到 ${sections.length} 个章节` : `共 ${manual.sections.length} 个章节`}</span>
        <Select
          className="manual-chapter-select"
          aria-label="跳转手册章节"
          placeholder="跳转到章节"
          options={sections.map(section => ({ value: section.id, label: section.title }))}
          onSelect={id => { window.location.hash = id }}
        />
      </div>

      <div className="manual-body">
        <aside className="manual-sidebar">
          <nav aria-label="使用手册目录">
            {groups.map(group => (
              <div className="manual-nav-group" key={group}>
                <div className="manual-nav-heading">{group}</div>
                {sections.filter(section => section.group === group).map(section => (
                  <a href={`#${section.id}`} key={section.id} title={section.title}>
                    <span>{String(manual.sections.indexOf(section) + 1).padStart(2, '0')}</span>
                    {section.title.split('：')[0]}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <a className="manual-back-top" href="#manual-top">回到顶部 ↑</a>
        </aside>

        <main className="manual-chapters" aria-label="使用手册正文">
          {sections.length === 0 && (
            <div className="manual-empty">
              <Empty description="没有找到相关章节，试试更短的关键词" />
              <Button onClick={() => setQuery('')}>清空搜索，查看完整手册</Button>
            </div>
          )}
          {sections.map(section => (
            <section className="manual-chapter" id={section.id} key={section.id} aria-labelledby={`${section.id}-title`}>
              <div className="manual-chapter-label">{String(manual.sections.indexOf(section) + 1).padStart(2, '0')} <span>{section.group}</span></div>
              <h2 id={`${section.id}-title`}>{section.title}</h2>
              <p className="manual-summary">{section.summary}</p>
              {section.entry && <div className="manual-entry"><strong>入口</strong><span>{section.entry}</span></div>}
              <div className="manual-chapter-content">{section.blocks.map((block, index) => <Block block={block} key={index} />)}</div>
            </section>
          ))}
        </main>
      </div>
      <footer className="manual-footer">洛图数据处理平台 · {manual.version} · 具体权限和可操作范围以当前页面为准</footer>
    </div>
  )
}
