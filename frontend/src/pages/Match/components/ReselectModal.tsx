import { useEffect, useRef, useState } from 'react'
import {
  Modal, Space, Alert, Descriptions, Typography, Tag, List, Button, Select, Empty,
  message,
} from 'antd'
import { LoadingOutlined } from '@ant-design/icons'
import type { MatchCandidateOut, MatchReviewDetail, ModelItem } from '../../../services/api'
import { getMatchReviewDetail, listModels, confirmMatch } from '../../../services/api'

const { Text } = Typography

// —— 下列常量与匹配页保持字符串完全一致，避免 layout 静态断言失败 ——
const MAPPING_HINT = '有可用 URL 线索时，纠错会同步覆盖对应 URL 映射，后续同链接将优先匹配到新型号。'
const SUCCESS_HINT = '已完成型号纠错；有可用 URL 线索时会同步更新 URL 映射'

type PriceFlag = 'ok' | 'high' | 'low' | 'no_history'
const priceFlagMeta: Record<PriceFlag, { label: string; color: string }> = {
  ok: { label: '正常', color: 'green' },
  high: { label: '偏高', color: 'red' },
  low: { label: '偏低', color: 'orange' },
  no_history: { label: '无历史', color: 'default' },
}

const matchSourceMeta = (source?: string | null) => {
  const map: Record<string, { label: string; color: string }> = {
    s0: { label: 'URL映射命中', color: 'blue' },
    historical: { label: '历史库命中', color: 'purple' },
    's0.5': { label: '规则命中', color: 'cyan' },
    s1: { label: '品牌字段匹配', color: 'green' },
    s2: { label: '标题品牌码匹配', color: 'green' },
    s3: { label: '标题品牌名匹配', color: 'green' },
    s4: { label: '型号码兜底匹配', color: 'orange' },
    manual: { label: '人工确认', color: 'blue' },
  }
  return source ? map[source] : undefined
}

const renderMatchSource = (source?: string | null) => {
  const entry = matchSourceMeta(source)
  if (!source) return <Tag color="default">未知</Tag>
  return entry ? <Tag color={entry.color}>{entry.label}</Tag> : <Tag>{source}</Tag>
}

const renderMatchStatus = (status: string) => {
  const meta: Record<string, { label: string; color: string }> = {
    pending: { label: '待确认', color: 'orange' },
    matched: { label: '已匹配', color: 'green' },
    url_matched: { label: '精准匹配', color: 'green' },
    confirmed: { label: '已人工确认', color: 'blue' },
    excluded: { label: '已排除', color: 'default' },
  }
  const m = meta[status] ?? { label: status, color: 'default' }
  return <Tag color={m.color}>{m.label}</Tag>
}

const isPlaceholderCode = (v?: string | null) => {
  const s = (v ?? '').trim()
  return s === '' || /^-+$/.test(s)
}
const hasDisplayModel = (b?: string | null, m?: string | null) =>
  !isPlaceholderCode(b) && !isPlaceholderCode(m)

interface ModelOption {
  id: number
  brand_code: string
  model_code: string
  brand_name?: string | null
  model_name?: string | null
}
const modelOptionFromCandidate = (c: MatchCandidateOut): ModelOption => ({
  id: c.model_id!,
  brand_code: c.brand_code || '',
  model_code: c.model_code || '',
  brand_name: null,
  model_name: null,
})
const modelOptionFromModel = (m: ModelItem): ModelOption => ({
  id: m.id,
  brand_code: m.brand_code || '',
  model_code: m.model_code || '',
  brand_name: m.brand_name ?? null,
  model_name: m.model_name ?? null,
})
const modelOptionLabel = (opt: ModelOption) => `[${opt.brand_code || '-'}] ${opt.model_code || '-'}`
const mergeModelOption = (list: ModelOption[], opt: ModelOption) =>
  list.some(x => x.id === opt.id) ? list : [opt, ...list]

export interface ReselectModalProps {
  open: boolean
  matchId: number | null
  onClose: () => void
  onSuccess: (matchId: number) => void
}

export default function ReselectModal({ open, matchId, onClose, onSuccess }: ReselectModalProps) {
  const [detail, setDetail] = useState<MatchReviewDetail | null>(null)
  const [modelId, setModelId] = useState<number | undefined>()
  const [options, setOptions] = useState<ModelOption[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)

  const reselectRequestSeqRef = useRef(0)
  const reselectSearchRequestSeqRef = useRef(0)
  const reselectDetailRef = useRef<MatchReviewDetail | null>(null)

  useEffect(() => {
    if (!open || matchId == null) return
    const requestSeq = reselectRequestSeqRef.current + 1
    reselectRequestSeqRef.current = requestSeq
    reselectSearchRequestSeqRef.current += 1
    reselectDetailRef.current = null
    setDetail(null)
    setModelId(undefined)
    setOptions([])
    setSearchLoading(false)
    setLoading(true)
    ;(async () => {
      try {
        const res = await getMatchReviewDetail(matchId)
        const d = res.data
        if (requestSeq !== reselectRequestSeqRef.current || d.id !== matchId) return
        const opts: ModelOption[] = []
        if (d.model_id && hasDisplayModel(d.brand_code, d.model_code)) {
          opts.push({
            id: d.model_id, brand_code: d.brand_code ?? '',
            model_code: d.model_code ?? '', brand_name: null, model_name: null,
          })
        }
        ;(d.candidates ?? []).forEach(c => {
          const o = modelOptionFromCandidate(c)
          if (!opts.some(x => x.id === o.id)) opts.push(o)
        })
        reselectDetailRef.current = d
        setDetail(d)
        setModelId(d.model_id ?? undefined)
        setOptions(opts)
      } catch {
        if (requestSeq === reselectRequestSeqRef.current) {
          message.error('纠错详情加载失败，请稍后重试')
        }
      } finally {
        if (requestSeq === reselectRequestSeqRef.current) setLoading(false)
      }
    })()
  }, [open, matchId])

  const handleModelSearch = async (keyword: string) => {
    if (!keyword.trim() || !detail) return
    const detailId = detail.id
    const searchSeq = reselectSearchRequestSeqRef.current + 1
    reselectSearchRequestSeqRef.current = searchSeq
    setSearchLoading(true)
    try {
      const res = await listModels({
        keyword, page: 1, page_size: 50,
        category_code: detail?.category_code || undefined,
      }).then(r => r.data)
      if (searchSeq !== reselectSearchRequestSeqRef.current ||
          reselectDetailRef.current?.id !== detailId) return
      setOptions((res.items ?? []).map(modelOptionFromModel))
    } finally {
      if (searchSeq === reselectSearchRequestSeqRef.current &&
          reselectDetailRef.current?.id === detailId) {
        setSearchLoading(false)
      }
    }
  }

  const handlePickCandidate = (c: MatchCandidateOut) => {
    const opt = modelOptionFromCandidate(c)
    setOptions(prev => mergeModelOption(prev, opt))
    setModelId(c.model_id ?? undefined)
  }

  const handleCancel = () => {
    if (submitting) return
    reselectRequestSeqRef.current += 1
    reselectSearchRequestSeqRef.current += 1
    reselectDetailRef.current = null
    setDetail(null)
    setModelId(undefined)
    setOptions([])
    setSearchLoading(false)
    onClose()
  }

  const handleOk = async () => {
    if (!detail) return
    if (!modelId) { message.warning('请选择要纠错的型号'); return }
    setSubmitting(true)
    try {
      await confirmMatch(detail.id, { model_id: modelId })
      message.success(SUCCESS_HINT)
      const id = detail.id
      reselectRequestSeqRef.current += 1
      reselectSearchRequestSeqRef.current += 1
      reselectDetailRef.current = null
      setDetail(null)
      setModelId(undefined)
      setOptions([])
      setSearchLoading(false)
      onSuccess(id)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="重新选择型号"
      open={open}
      onCancel={handleCancel}
      onOk={handleOk}
      okText="确认纠错"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: loading || !detail || !modelId }}
      destroyOnClose
      width={720}
    >
      {loading ? (
        <Space><LoadingOutlined /> <span>正在加载纠错详情...</span></Space>
      ) : detail ? (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert type="info" showIcon message={MAPPING_HINT} />
          <Descriptions size="small" bordered column={2}>
            <Descriptions.Item label="商品名称" span={2}>{detail.item_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="当前型号">
              {hasDisplayModel(detail.brand_code, detail.model_code)
                ? <Text code>[{detail.brand_code}] {detail.model_code}</Text>
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">{renderMatchStatus(detail.match_status)}</Descriptions.Item>
            <Descriptions.Item label="来源">{renderMatchSource(detail.match_source)}</Descriptions.Item>
            <Descriptions.Item label="价格预警">
              {detail.price_flag
                ? <Tag color={priceFlagMeta[detail.price_flag].color}>{priceFlagMeta[detail.price_flag].label}</Tag>
                : <Tag color="default">-</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="参考均价">
              {detail.price_ref != null ? `¥${detail.price_ref.toLocaleString()}` : '-'}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Text strong>候选型号</Text>
            {(detail.candidates ?? []).length > 0 ? (
              <List
                size="small"
                dataSource={detail.candidates ?? []}
                renderItem={(c: MatchCandidateOut) => (
                  <List.Item
                    actions={[
                      <Button key="pick" size="small"
                              type={modelId === c.model_id ? 'primary' : 'link'}
                              onClick={() => handlePickCandidate(c)}>选用</Button>,
                    ]}
                  >
                    <Text code>[{c.brand_code || '-'}] {c.model_code || '-'}</Text>
                  </List.Item>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选型号，可搜索其他型号" />
            )}
          </div>

          <div>
            <Text strong>搜索其他型号</Text>
            <Select
              showSearch allowClear filterOption={false}
              placeholder="搜索/选择纠错型号"
              style={{ width: '100%', marginTop: 8 }}
              value={modelId}
              loading={searchLoading}
              onSearch={handleModelSearch}
              onChange={v => setModelId(v)}
              options={options.map(o => ({ label: modelOptionLabel(o), value: o.id }))}
            />
          </div>
        </Space>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="纠错详情加载失败" />
      )}
    </Modal>
  )
}
