import { Button, Modal, Space, Typography } from 'antd'

export function FilterReason({ reason }: { reason?: string | null }) {
  if (!reason?.trim()) return <span>未记录过滤原因</span>
  return <Space direction="vertical" size={0} style={{ width: '100%' }}>
    <Typography.Text style={{ maxWidth: 320 }} ellipsis={{ tooltip: reason }}>{reason}</Typography.Text>
    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => Modal.info({
      title: '完整过滤原因',
      width: 680,
      okText: '知道了',
      content: <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{reason}</Typography.Paragraph>,
    })}>查看完整原因</Button>
  </Space>
}
