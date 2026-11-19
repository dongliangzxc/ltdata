import type { ManualDocument, ManualSection } from './types'

export function searchSections(sections: ManualSection[], query: string): ManualSection[]
export function renderManualMarkdown(document: ManualDocument): string
