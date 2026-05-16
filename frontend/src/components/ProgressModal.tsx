import { Modal, Progress, Typography, Space } from 'antd'

interface ProgressModalProps {
  visible: boolean
  title: string
  progress: number
  errorMsg?: string
}

/**
 * 通用进度条 Modal。
 * - 进度 < 100 且无错误：显示 active 进度条 + "完成后自动关闭" 提示
 * - progress === 100 且无错误：进度条变 success（绿色），调用方负责关闭
 * - errorMsg 有值：显示错误文字，调用方负责关闭
 */
export default function ProgressModal({ visible, title, progress, errorMsg }: ProgressModalProps) {
  return (
    <Modal
      open={visible}
      title={title}
      footer={null}
      closable={false}
      maskClosable={false}
      width={420}
      centered
    >
      {errorMsg ? (
        <Typography.Text type="danger">{errorMsg}</Typography.Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Progress
            percent={progress}
            status={progress >= 100 ? 'success' : 'active'}
            strokeColor={progress >= 100 ? undefined : { from: '#108ee9', to: '#87d068' }}
          />
          {progress < 100 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              完成后自动关闭...
            </Typography.Text>
          )}
        </Space>
      )}
    </Modal>
  )
}
