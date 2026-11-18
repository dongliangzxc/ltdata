import type { SupplementCleanTaskResult } from '../../services/api'

export function supplementFeedback(result: SupplementCleanTaskResult) {
  const counts = `新增 ${result.inserted_rows} 条，重复跳过 ${result.duplicate_rows} 条`
  if (result.match_status === 'queued') {
    return {
      type: 'info' as const,
      message: `文件已接收，已加入清洗队列：${counts}`,
      description: '清洗、批量匹配和价格审核尚未完成。可关闭窗口，在任务列表查看进度；失败后点击重试，无需重复上传文件。',
    }
  }
  return {
    type: 'success' as const,
    message: `补充完成：${counts}`,
    description: '本次新增数据已完成处理，原有结果保留。',
  }
}
