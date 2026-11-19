export type ManualBlock =
  | { type: 'paragraph' | 'heading'; text: string }
  | { type: 'steps' | 'list'; items: string[] }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'note'; title: string; text: string; tone: 'info' | 'warning' }

export interface ManualSection {
  id: string
  title: string
  group: string
  summary: string
  entry: string | null
  keywords: string[]
  blocks: ManualBlock[]
}

export interface ManualDocument {
  title: string
  version: string
  updatedAt: string
  audience: string
  intro: string
  quickLinks: { title: string; description: string; target: string }[]
  sections: ManualSection[]
}
