import { Card, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import type { MatchReviewDetail } from '../../../services/api'

const { Text } = Typography

type Props = {
  detail: MatchReviewDetail
}

export default function AttributeInsightCard({ detail }: Props) {
  const metadataSpecs = detail.metadata_specs ?? []
  const modelSpecs = detail.model_specs ?? []
  const matchAttrs = detail.match_attrs ?? []

  return (
    <Card size="small" title="品类属性" styles={{ body: { padding: 8 } }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div>
          <Text strong>品类字段要求</Text>
          {metadataSpecs.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无品类字段定义" />
          ) : (
            <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
              {metadataSpecs.map(spec => (
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
                    {spec.spec_values ? <Text type="secondary">{spec.spec_values}</Text> : <Text type="secondary">不限枚举</Text>}
                  </Space>
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </div>

        <div>
          <Text strong>当前型号规格</Text>
          {modelSpecs.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前型号暂无规格" />
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
            <Space wrap style={{ marginTop: 8 }}>
              {matchAttrs.map(attr => (
                <Tag key={attr.id} color="blue">{attr.attr_name}：{attr.attr_value}</Tag>
              ))}
            </Space>
          )}
        </div>
      </Space>
    </Card>
  )
}
