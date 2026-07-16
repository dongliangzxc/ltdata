import { useEffect, useState } from 'react'
import { Alert, Form, Input, Modal, message } from 'antd'
import {
  createBrand,
  type BrandItem,
  type CreateBrandPayload,
} from '../services/api'

type CreateBrandFormValues = CreateBrandPayload & {
  alias_name?: string
}

type CreateBrandModalProps = {
  open: boolean
  onCancel: () => void
  onCreated?: (brand: BrandItem) => void
  initialBrandName?: string | null
  allowAlias?: boolean
}

const trimOrUndefined = (value?: string | null) => {
  const trimmed = (value ?? '').trim()
  return trimmed || undefined
}

export default function CreateBrandModal({
  open,
  onCancel,
  onCreated,
  initialBrandName,
  allowAlias = true,
}: CreateBrandModalProps) {
  const [form] = Form.useForm<CreateBrandFormValues>()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    form.resetFields()
    form.setFieldsValue({
      brand_name: trimOrUndefined(initialBrandName),
      alias_name: undefined,
    })
  }, [form, initialBrandName, open])

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const aliasName = trimOrUndefined(values.alias_name)
      const payload: CreateBrandPayload = {
        brand_code: values.brand_code.trim(),
        brand_name: trimOrUndefined(values.brand_name) ?? null,
        alias_name: allowAlias ? aliasName ?? null : null,
      }
      const res = await createBrand(payload)
      const created = res.data
      message.success('品牌创建成功')
      onCreated?.(created)
      form.resetFields()
    } catch {
      // errors shown by axios interceptor
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="新建品牌"
      open={open}
      onOk={handleOk}
      confirmLoading={saving}
      onCancel={() => { form.resetFields(); onCancel() }}
      okText="创建"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item
          label="品牌码"
          name="brand_code"
          rules={[
            { required: true, message: '请输入品牌码' },
            {
              validator: (_, value: string | undefined) => {
                const trimmed = (value ?? '').trim()
                if (!trimmed) return Promise.resolve()
                if (/^-+$/.test(trimmed)) return Promise.reject(new Error('品牌码不能为占位符'))
                return Promise.resolve()
              },
            },
          ]}
        >
          <Input placeholder="如 DJI / SONY / apple" autoFocus />
        </Form.Item>
        <Form.Item label="品牌名称" name="brand_name">
          <Input placeholder="如 大疆 / 索尼 / Apple" />
        </Form.Item>
        {allowAlias && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="品牌别名选填；如果创建失败，不影响品牌创建，可后续在品牌管理页补充。"
            />
            <Form.Item label="品牌别名" name="alias_name">
              <Input placeholder="如 Sony / SONY INC / 索尼" />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  )
}
