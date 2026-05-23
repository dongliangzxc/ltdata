import { Modal, Progress, Typography, Space } from 'antd'

interface ProgressModalProps {
  visible: boolean
  title: string
  progress: number
  errorMsg?: string
  stageLabel?: string | null
  totalRows?: number | null
  processedRows?: number | null
  insertedRows?: number | null
  skippedRows?: number | null
  onClose?: () => void
}

/**
 * 通用进度条 Modal。
 * - 进度 < 100 且无错误：显示 active 进度条 + "完成后自动关闭" 提示
 * - progress === 100 且无错误：进度条变 success（绿色），调用方负责关闭
 * - errorMsg 有值：显示错误文字，调用方负责关闭
 */
export default function ProgressModal({
  visible,
  title,
  progress,
  errorMsg,
  stageLabel,
  totalRows,
  processedRows,
  insertedRows,
  skippedRows,
  onClose,
}: ProgressModalProps) {
  const hasRowStats = totalRows != null || processedRows != null || insertedRows != null || skippedRows != null

  return (
    <Modal
      open={visible}
      title={title}
      closable={!!onClose}
      onCancel={onClose}
      width={460}
      centered
      footer={null}
      maskClosable={false}
    >
      {errorMsg ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          {stageLabel && <Typography.Text>{stageLabel}</Typography.Text>}
          <Typography.Text type="danger">{errorMsg}</Typography.Text>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          {stageLabel && <Typography.Text>{stageLabel}</Typography.Text>}
          <Progress
            percent={progress}
            status={progress >= 100 ? 'success' : 'active'}
            strokeColor={progress >= 100 ? undefined : { from: '#108ee9', to: '#87d068' }}
          />
          {hasRowStats && (
            <Space direction="vertical" size={2}>
              {processedRows != null && (
                <Typography.Text>
                  已处理：{processedRows}{totalRows != null ? ` / ${totalRows}` : ''} 行
                </Typography.Text>
              )}
              {processedRows == null && totalRows != null && (
                <Typography.Text>总行数：{totalRows} 行</Typography.Text>
              )}
              {insertedRows != null && <Typography.Text>已插入：{insertedRows} 行</Typography.Text>}
              {skippedRows != null && <Typography.Text>已跳过：{skippedRows} 行</Typography.Text>}
            </Space>
          )}
          {progress < 100 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {onClose ? '关闭或刷新页面后，可在上传处理任务中继续查看进度' : '刷新页面后，可在上传处理任务中继续查看进度'}
            </Typography.Text>
          )}
        </Space>
      )}
    </Modal>
  )
}
