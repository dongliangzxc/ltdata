import { Button, Card, List, message, Modal, Space, Tag, Typography } from 'antd'
import { useRequest } from 'ahooks'
import {
  confirmSameTitleMatches,
  excludeSameTitleMatches,
  previewSameTitleMatches,
} from '../../../services/api'
import type { MatchReviewDetail, SameTitlePreview } from '../../../services/api'

const { Text } = Typography

const STATUS_LABELS: Record<string, string> = {
  pending: '待确认',
  text_only: 'URL待确认',
  disputed: '争议',
  confirmed: '已确认',
  matched: '已匹配',
  url_matched: '精准匹配',
  excluded: '已排除',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'orange',
  text_only: 'gold',
  disputed: 'red',
  confirmed: 'blue',
  matched: 'green',
  url_matched: 'green',
  excluded: 'default',
}

const includeStatuses = ['pending', 'text_only', 'disputed']

type Props = {
  detail: MatchReviewDetail
  selectedModelId?: number
  reason?: string
  onDone: () => void
}

const formatNumber = (value?: number | null) => (
  value != null ? value.toLocaleString() : '-'
)

const renderStatus = (status: string) => (
  <Tag color={STATUS_COLORS[status] ?? 'default'}>{STATUS_LABELS[status] ?? status}</Tag>
)

const renderPreviewContent = (preview: SameTitlePreview) => (
  <Space direction="vertical" size={12} style={{ width: '100%' }}>
    <Text>
      相同 case 共 {formatNumber(preview.total)} 条，可处理 {formatNumber(preview.actionable_count)} 条。
    </Text>
    <List
      size="small"
      dataSource={preview.items ?? []}
      locale={{ emptyText: '暂无预览数据' }}
      renderItem={item => (
        <List.Item>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Space wrap size={4}>
              {renderStatus(item.match_status)}
              <Tag color="blue">{item.brand_raw || '无原品牌'}</Tag>
              <Text type="secondary">销量 {formatNumber(item.sales_qty)}</Text>
              <Text code>{item.model_code ? `[${item.brand_code ?? '-'}] ${item.model_code}` : '未匹配型号'}</Text>
            </Space>
            <Text ellipsis title={item.item_name || undefined}>{item.item_name || '-'}</Text>
          </Space>
        </List.Item>
      )}
    />
  </Space>
)

export default function SameTitleBatchActions({ detail, selectedModelId, reason, onDone }: Props) {
  const { data, loading, refresh } = useRequest(
    () => previewSameTitleMatches(detail.id).then(r => r.data),
    { refreshDeps: [detail.id] }
  )

  const fetchLatestPreview = async () => previewSameTitleMatches(detail.id).then(r => r.data)

  const openPreview = async () => {
    const preview = data ?? await fetchLatestPreview()
    Modal.info({
      title: '相同 case 预览',
      width: 760,
      content: renderPreviewContent(preview),
    })
  }

  const handleBatchConfirm = async () => {
    const modelId = selectedModelId ?? detail.model_id ?? undefined
    if (!modelId) {
      message.warning('请先选择型号')
      return
    }

    const preview = await fetchLatestPreview()
    Modal.confirm({
      title: '确认批量确认相同标题？',
      content: (
        <Space direction="vertical" size={8}>
          <Text>本次将处理可处理数据 {formatNumber(preview.actionable_count)} / {formatNumber(preview.total)} 条。</Text>
          <Text type="secondary">
            仅处理 pending / text_only / disputed 状态，已确认、已排除等结果不会被覆盖。
          </Text>
        </Space>
      ),
      okText: '批量确认',
      onOk: async () => {
        const result = await confirmSameTitleMatches(detail.id, {
          model_id: modelId,
          include_statuses: includeStatuses,
        }).then(r => r.data)
        message.success(`已批量确认 ${result.affected_count} 条`)
        refresh()
        onDone()
      },
    })
  }

  const handleBatchExclude = async () => {
    const preview = await fetchLatestPreview()
    Modal.confirm({
      title: '确认批量排除相同标题？',
      content: (
        <Space direction="vertical" size={8}>
          <Text>本次将排除可处理数据 {formatNumber(preview.actionable_count)} / {formatNumber(preview.total)} 条。</Text>
          <Text type="secondary">
            排除后的数据不会发布到分析库，也不会写入 URL 映射库。仅处理 pending / text_only / disputed 状态，已确认、已排除等结果不会被覆盖。
          </Text>
        </Space>
      ),
      okText: '批量排除',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await excludeSameTitleMatches(detail.id, {
          reason,
          include_statuses: includeStatuses,
        }).then(r => r.data)
        message.success(`已批量排除 ${result.affected_count} 条`)
        refresh()
        onDone()
      },
    })
  }

  const hasData = !!data && data.total > 0
  const hasActionable = !!data && data.actionable_count > 0

  return (
    <Card size="small" title="相同 case 批量处理" styles={{ body: { padding: 8 } }}>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Text type="secondary">
          相同 case 共 {formatNumber(data?.total)} 条，可批量处理 {formatNumber(data?.actionable_count)} 条。
        </Text>
        <Space wrap>
          <Button loading={loading} disabled={!hasData} onClick={openPreview}>预览</Button>
          <Button type="primary" loading={loading} disabled={!hasActionable} onClick={handleBatchConfirm}>
            批量确认相同标题
          </Button>
          <Button danger loading={loading} disabled={!hasActionable} onClick={handleBatchExclude}>
            批量排除相同标题
          </Button>
        </Space>
      </Space>
    </Card>
  )
}
