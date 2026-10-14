import { useState } from 'react'
import { Button, Modal, Alert, Typography, message } from 'antd'
import { DeleteOutlined, ExclamationCircleFilled } from '@ant-design/icons'

const { Text } = Typography

type CountResponse = { data: { category_code: string; count: number } }
type DeleteResponse = { data: { category_code: string; deleted: number } }

type Props = {
  categoryCode?: string
  categoryLabel?: string
  itemLabel: string
  description: string
  getCount: (categoryCode: string) => Promise<CountResponse>
  bulkDelete: (categoryCode: string) => Promise<DeleteResponse>
  onSuccess: () => void
}

export default function BulkDeleteByCategory({
  categoryCode,
  categoryLabel,
  itemLabel,
  description,
  getCount,
  bulkDelete,
  onSuccess,
}: Props) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState<number | null>(null)
  const [countLoading, setCountLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const openModal = async () => {
    if (!categoryCode) return
    setOpen(true)
    setCount(null)
    setCountLoading(true)
    try {
      const res = await getCount(categoryCode)
      setCount(res.data.count)
    } catch {
      // handled by interceptor
    } finally {
      setCountLoading(false)
    }
  }

  const handleConfirm = async () => {
    if (!categoryCode) return
    setDeleting(true)
    try {
      const res = await bulkDelete(categoryCode)
      message.success(`已删除 ${res.data.deleted} 条${itemLabel}`)
      setOpen(false)
      onSuccess()
    } catch {
      // handled by interceptor
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Button
        danger
        icon={<DeleteOutlined />}
        disabled={!categoryCode}
        title={categoryCode ? undefined : '请先选择品类'}
        onClick={openModal}
      >
        一键删除
      </Button>
      <Modal
        title={(
          <span>
            <ExclamationCircleFilled style={{ color: '#faad14', marginRight: 8 }} />
            按品类一键删除
          </span>
        )}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={handleConfirm}
        okText="确认删除"
        okButtonProps={{ danger: true, disabled: countLoading || count === 0 }}
        confirmLoading={deleting}
        destroyOnClose
        width={460}
      >
        <Alert
          type="error"
          showIcon
          message={(
            <span>
              将删除 <Text strong>{categoryLabel || categoryCode}</Text> 品类下的全部{itemLabel}
              {countLoading
                ? '（统计中…）'
                : count != null
                  ? <>，共 <Text strong style={{ color: '#cf1322' }}>{count}</Text> 条</>
                  : null}
            </span>
          )}
          description={description}
        />
      </Modal>
    </>
  )
}
