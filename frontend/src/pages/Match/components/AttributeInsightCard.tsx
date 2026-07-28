import { useMemo, useState } from 'react'
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Col,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { createMetadata, type MatchReviewDetail, type MetadataSpecPayload } from '../../../services/api'

const { Text } = Typography

type Props = {
  detail: MatchReviewDetail
  onMetadataChanged?: () => Promise<void> | void
}

export default function AttributeInsightCard({ detail, onMetadataChanged }: Props) {
  const metadataSpecs = detail.metadata_specs ?? []
  const modelSpecs = detail.model_specs ?? []
  const matchAttrs = detail.match_attrs ?? []
  const [specSearch, setSpecSearch] = useState('')
  const [metadataModalOpen, setMetadataModalOpen] = useState(false)
  const [metadataSaving, setMetadataSaving] = useState(false)
  const [metadataForm] = Form.useForm<MetadataSpecPayload>()

  const currentCategoryCode = detail.category_code?.trim() || undefined
  const filteredMetadataSpecs = useMemo(() => {
    const keyword = specSearch.trim().toLowerCase()
    if (!keyword) return metadataSpecs
    return metadataSpecs.filter(spec => spec.spec_name.toLowerCase().includes(keyword))
  }, [metadataSpecs, specSearch])

  const openMetadataModal = () => {
    if (!currentCategoryCode) {
      message.warning('当前商品缺少品类，无法新建字段要求')
      return
    }
    if (!onMetadataChanged) {
      message.warning('当前详情不可维护字段要求')
      return
    }
    metadataForm.resetFields()
    metadataForm.setFieldsValue({
      category_code: currentCategoryCode,
      spec_type: '文本型',
      required: false,
      single_select: true,
      decimal_places: null,
      spec_values: null,
    })
    setMetadataModalOpen(true)
  }

  const handleCreateMetadata = async () => {
    if (!currentCategoryCode || !onMetadataChanged) return
    const values = await metadataForm.validateFields()
    const payload: MetadataSpecPayload = {
      category_code: currentCategoryCode,
      spec_name: values.spec_name.trim(),
      spec_type: values.spec_type,
      spec_values: values.spec_values?.trim() || null,
      required: Boolean(values.required),
      decimal_places: values.decimal_places ?? null,
      single_select: values.single_select ?? true,
    }
    setMetadataSaving(true)
    try {
      await createMetadata(payload)
      message.success('字段要求已新建')
      setMetadataModalOpen(false)
      await onMetadataChanged()
      setSpecSearch('')
    } finally {
      setMetadataSaving(false)
    }
  }

  return (
    <Card size="small" title="品类属性" styles={{ body: { padding: 8 } }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div>
          <Space style={{ width: '100%', justifyContent: 'space-between' }} align="center">
            <Text strong>品类字段要求</Text>
            <Space>
              <Input
                allowClear
                size="small"
                prefix={<SearchOutlined />}
                placeholder="搜索字段要求"
                value={specSearch}
                onChange={event => setSpecSearch(event.target.value)}
                style={{ width: 220 }}
              />
              <Button size="small" icon={<PlusOutlined />} onClick={openMetadataModal} disabled={!currentCategoryCode || !onMetadataChanged}>
                新建字段要求
              </Button>
            </Space>
          </Space>
          {filteredMetadataSpecs.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无品类字段定义" />
          ) : (
            <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
              {filteredMetadataSpecs.map(spec => (
                <Descriptions.Item
                  key={spec.id}
                  label={(
                    <Space size={4}>
                      <span>{spec.spec_name}</span>
                      {spec.required && <Tag color="red">必填</Tag>}
                    </Space>
                  )}
                >
                  <Space wrap size={4}>
                    <Tag>{spec.spec_type}</Tag>
                    {spec.spec_values ? <Text type="secondary">{spec.spec_values}</Text> : <Text type="secondary">无可选值</Text>}
                    {spec.single_select ? <Tag color="blue">单选</Tag> : <Tag color="cyan">多选</Tag>}
                  </Space>
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </div>

        <Modal
          title="新建字段要求"
          open={metadataModalOpen}
          onOk={handleCreateMetadata}
          onCancel={() => setMetadataModalOpen(false)}
          confirmLoading={metadataSaving}
          okText="新建"
          cancelText="取消"
          destroyOnClose
        >
          <Form form={metadataForm} layout="vertical">
            <Form.Item label="当前品类" name="category_code">
              <Input disabled />
            </Form.Item>
            <Form.Item
              label="字段名称"
              name="spec_name"
              rules={[{ required: true, whitespace: true, message: '请输入字段名称' }]}
            >
              <Input placeholder="例如：佩戴方式" />
            </Form.Item>
            <Form.Item label="字段类型" name="spec_type" rules={[{ required: true, message: '请选择字段类型' }]}>
              <Select
                options={[
                  { value: '文本型', label: '文本型' },
                  { value: '数值型', label: '数值型' },
                  { value: '枚举型', label: '枚举型' },
                ]}
              />
            </Form.Item>
            <Form.Item label="可选值" name="spec_values">
              <Input.TextArea rows={3} placeholder="多个值用逗号分隔" />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item label="小数位" name="decimal_places">
                  <InputNumber style={{ width: '100%' }} min={0} max={6} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="是否单选" name="single_select" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="是否必填" name="required" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Form>
        </Modal>

        <div>
          <Text strong>当前型号属性</Text>
          {modelSpecs.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无当前型号属性" />
          ) : (
            <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
              {modelSpecs.map(spec => (
                <Descriptions.Item key={spec.id} label={spec.spec_name}>
                  {spec.spec_value || '-'}
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </div>

        <div>
          <Text strong>本条自动补充属性</Text>
          {matchAttrs.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无自动补充属性" />
          ) : (
            <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
              {matchAttrs.map(attr => (
                <Descriptions.Item key={attr.id} label={attr.attr_name}>
                  {attr.attr_value || '-'}
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </div>
      </Space>
    </Card>
  )
}
