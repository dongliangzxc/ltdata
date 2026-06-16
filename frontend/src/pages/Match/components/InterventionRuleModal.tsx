import { Button, Form, Input, InputNumber, List, message, Modal, Popconfirm, Select, Space, Tabs, Tag, Typography } from 'antd'
import { useEffect } from 'react'
import { useRequest } from 'ahooks'
import {
  createInterventionRule,
  deleteInterventionRule,
  listInterventionRules,
  updateInterventionRule,
} from '../../../services/api'
import type { InterventionRuleItem, MatchReviewDetail } from '../../../services/api'

const { Text } = Typography

const textAreaStyle = { minHeight: 72 }

type Props = {
  open: boolean
  categoryCode?: string | null
  detail?: MatchReviewDetail | null
  onClose: () => void
  onRulesChanged: () => void
}

type FormValues = {
  name: string
  action: 'filter' | 'allow'
  priority: number
  item_name_contains_any?: string
  brand_in?: string
  item_name_not_contains_any?: string
}

const splitValues = (value?: string) => (value || '').split(/[\n,，、]+/).map(item => item.trim()).filter(Boolean)

const getFirstToken = (value?: string | null) => (
  (value || '')
    .split(/[\s,，、/|｜;；:：()（）【】\[\]{}<>《》"'“”‘’]+/)
    .map(item => item.trim())
    .find(Boolean) || ''
)

const buildConditions = (values: FormValues) => {
  const conditions: Record<string, string[]> = {}
  const nameContains = splitValues(values.item_name_contains_any)
  const brandIn = splitValues(values.brand_in)
  const nameNotContains = splitValues(values.item_name_not_contains_any)
  if (nameContains.length) conditions.item_name_contains_any = nameContains
  if (brandIn.length) conditions.brand_in = brandIn
  if (nameNotContains.length) conditions.item_name_not_contains_any = nameNotContains
  return conditions
}

export default function InterventionRuleModal({ open, categoryCode, detail, onClose, onRulesChanged }: Props) {
  const [form] = Form.useForm<FormValues>()
  const normalizedCategoryCode = categoryCode || undefined

  const { data, loading, refresh } = useRequest(
    () => listInterventionRules({ category_code: normalizedCategoryCode }).then(r => r.data),
    {
      ready: open && Boolean(normalizedCategoryCode),
      refreshDeps: [open, normalizedCategoryCode],
    },
  )

  useEffect(() => {
    if (!open) return
    const firstToken = getFirstToken(detail?.item_name)
    form.resetFields()
    form.setFieldsValue({
      name: firstToken ? `过滤：${firstToken}` : '过滤：',
      action: 'filter',
      priority: 100,
      item_name_contains_any: firstToken,
      brand_in: detail?.brand_raw || undefined,
      item_name_not_contains_any: undefined,
    })
  }, [detail, form, open])

  const notifyRulesChanged = () => {
    refresh()
    onRulesChanged()
  }

  const handleToggleActive = async (rule: InterventionRuleItem) => {
    await updateInterventionRule(rule.id, { is_active: rule.is_active ? 0 : 1 })
    message.success(rule.is_active ? '已禁用规则' : '已启用规则')
    notifyRulesChanged()
  }

  const handleDelete = async (rule: InterventionRuleItem) => {
    await deleteInterventionRule(rule.id)
    message.success('已删除规则')
    notifyRulesChanged()
  }

  const handleCreate = async () => {
    if (!normalizedCategoryCode) {
      message.warning('当前任务缺少品类，无法新增干预规则')
      return
    }
    const values = await form.validateFields()
    const conditions = buildConditions(values)
    if (!Object.keys(conditions).length) {
      message.warning('至少填写一个干预条件')
      return
    }
    await createInterventionRule({
      name: values.name,
      category_code: normalizedCategoryCode,
      action: values.action,
      priority: values.priority,
      conditions,
    })
    message.success('规则已新增')
    form.setFieldsValue({
      name: '过滤：',
      action: 'filter',
      priority: 100,
      item_name_contains_any: undefined,
      brand_in: undefined,
      item_name_not_contains_any: undefined,
    })
    notifyRulesChanged()
  }

  const renderRule = (rule: InterventionRuleItem) => (
    <List.Item
      actions={[
        <Button key="toggle" size="small" onClick={() => handleToggleActive(rule)}>
          {rule.is_active ? '禁用' : '启用'}
        </Button>,
        <Popconfirm key="delete" title="确认删除此规则？" onConfirm={() => handleDelete(rule)}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>,
      ]}
    >
      <List.Item.Meta
        title={
          <Space wrap size={6}>
            <Text strong>{rule.name}</Text>
            <Tag color={rule.action === 'filter' ? 'red' : 'green'}>{rule.action === 'filter' ? '过滤' : '放行'}</Tag>
            <Tag color={rule.is_active ? 'blue' : 'default'}>{rule.is_active ? '启用' : '禁用'}</Tag>
            <Text type="secondary">优先级 {rule.priority}</Text>
          </Space>
        }
        description={rule.summary || '暂无条件摘要'}
      />
    </List.Item>
  )

  return (
    <Modal
      title="干扰项规则"
      open={open}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnClose
    >
      {!normalizedCategoryCode ? (
        <Text type="secondary">当前任务缺少品类，无法加载或新增干预规则。</Text>
      ) : (
        <Tabs
          items={[
            {
              key: 'list',
              label: '当前品类规则',
              children: (
                <List
                  loading={loading}
                  dataSource={data ?? []}
                  rowKey="id"
                  locale={{ emptyText: '当前品类暂无干预规则' }}
                  renderItem={renderRule}
                />
              ),
            },
            {
              key: 'create',
              label: '快速新增',
              children: (
                <Form form={form} layout="vertical" onFinish={handleCreate}>
                  <Form.Item label="规则名称" name="name" rules={[{ required: true, message: '请输入规则名称' }]}>
                    <Input placeholder="例如：过滤：赠品" />
                  </Form.Item>
                  <Space align="start" size={16} wrap>
                    <Form.Item label="动作" name="action" rules={[{ required: true, message: '请选择动作' }]}>
                      <Select
                        style={{ width: 140 }}
                        options={[
                          { value: 'filter', label: '过滤' },
                          { value: 'allow', label: '放行' },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item label="优先级" name="priority" rules={[{ required: true, message: '请输入优先级' }]}>
                      <InputNumber min={1} max={9999} style={{ width: 140 }} />
                    </Form.Item>
                  </Space>
                  <Form.Item label="商品名称包含任一" name="item_name_contains_any">
                    <Input.TextArea placeholder="每行或用逗号分隔多个关键词" style={textAreaStyle} />
                  </Form.Item>
                  <Form.Item label="品牌在列表中" name="brand_in">
                    <Input.TextArea placeholder="每行或用逗号分隔多个品牌" style={textAreaStyle} />
                  </Form.Item>
                  <Form.Item label="商品名称不包含任一" name="item_name_not_contains_any">
                    <Input.TextArea placeholder="每行或用逗号分隔多个排除关键词" style={textAreaStyle} />
                  </Form.Item>
                  <Space>
                    <Button type="primary" htmlType="submit">新增规则</Button>
                    <Button onClick={() => form.resetFields()}>重置</Button>
                  </Space>
                </Form>
              ),
            },
          ]}
        />
      )}
    </Modal>
  )
}
