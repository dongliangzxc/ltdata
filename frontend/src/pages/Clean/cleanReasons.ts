const STATUS_LABELS: Record<string, string> = {
  matched: '已匹配', url_matched: '精准匹配', confirmed: '人工确认',
  pending: '待确认', text_only: 'URL待确认', disputed: '争议复核',
  excluded: '已排除', ignored: '已忽略', invalid_model: '型号无效',
}

export function cleanStatusLabel(status?: string | null): string {
  return status ? STATUS_LABELS[status] || '其他状态' : '未生成结果'
}
