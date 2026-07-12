import { useState, useMemo, useEffect } from 'react'
import {
  Card, Space, Select, Input, Button, Tabs, Table, Typography, Badge, Row, Col, message,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listCleanJobs, updateMatchCoefficient, type CleanJobItem, type ReviewedMatchResultOut,
         type MatchResultsTab } from '../../services/api'
import { buildMatchResultsColumns } from './columns'
import { useMatchResultsQuery } from './useMatchResultsQuery'
import ReselectModal from '../Match/components/ReselectModal'

const { Text } = Typography

const MATCH_SOURCE_OPTIONS = [
  { value: 's0',         label: 'URL映射命中' },
  { value: 's0.2',       label: '历史库(旧)' },
  { value: 'historical', label: '历史库命中' },
  { value: 's0.5',       label: '规则命中' },
  { value: 's1',         label: '品牌字段匹配' },
  { value: 's2',         label: '标题品牌码匹配' },
  { value: 's3',         label: '标题品牌名匹配' },
  { value: 's4',         label: '型号码兜底' },
  { value: 'manual',     label: '人工确认' },
]

const PRICE_FLAG_OPTIONS = [
  { value: 'below',  label: '偏低' },
  { value: 'above',  label: '偏高' },
  { value: 'normal', label: '正常' },
  { value: 'none',   label: '无预警' },
]

export default function MatchResultsPage() {
  const { state, setState, reset, data, loading, refresh } = useMatchResultsQuery()
  const [reselectOpen, setReselectOpen] = useState(false)
  const [reselectMatchId, setReselectMatchId] = useState<number | null>(null)
  const [keywordInput, setKeywordInput] = useState<string>(state.keyword ?? '')
  const [coefficientDrafts, setCoefficientDrafts] = useState<Record<number, number | null>>({})
  const [editedCoefficientIds, setEditedCoefficientIds] = useState<Set<number>>(new Set())
  const [savingCoefficientIds, setSavingCoefficientIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    setKeywordInput(state.keyword ?? '')
  }, [state.keyword])

  useEffect(() => {
    setCoefficientDrafts(prev => {
      const next = { ...prev }
      for (const item of data?.items ?? []) {
        if (!(item.id in next)) next[item.id] = item.sales_coefficient ?? null
      }
      return next
    })
  }, [data?.items])

  const handleCoefficientChange = (matchId: number, value: number | null) => {
    setCoefficientDrafts(prev => ({ ...prev, [matchId]: value }))
    setEditedCoefficientIds(prev => new Set(prev).add(matchId))
  }

  const handleSaveCoefficient = async (matchId: number) => {
    const coefficient = coefficientDrafts[matchId] ?? null
    setSavingCoefficientIds(prev => new Set(prev).add(matchId))
    try {
      const res = await updateMatchCoefficient(matchId, coefficient)
      setCoefficientDrafts(prev => ({ ...prev, [matchId]: res.data.sales_coefficient ?? null }))
      setEditedCoefficientIds(prev => { const next = new Set(prev); next.delete(matchId); return next })
      message.success(coefficient == null ? '已清除调整系数' : '已保存调整系数')
      refresh()
    } catch (error) {
      console.error(error)
      message.error('保存调整系数失败')
    } finally {
      setSavingCoefficientIds(prev => { const next = new Set(prev); next.delete(matchId); return next })
    }
  }

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const jobOptions = useMemo(
    () => (jobsData ?? []).map((j: CleanJobItem) => ({
      value: j.id,
      label: `#${j.id} · ${j.task_name || '未命名任务'}`,
    })),
    [jobsData],
  )

  const columns = useMemo(
    () => buildMatchResultsColumns({
      coefficientDrafts,
      editedCoefficientIds,
      savingCoefficientIds,
      onCoefficientChange: handleCoefficientChange,
      onSaveCoefficient: handleSaveCoefficient,
      onReselect: (row: ReviewedMatchResultOut) => {
        setReselectMatchId(row.id)
        setReselectOpen(true)
      },
    }),
    [coefficientDrafts, editedCoefficientIds, savingCoefficientIds],
  )

  const counts = data?.counts ?? { all: 0, pending_review: 0, confirmed: 0 }
  const items: ReviewedMatchResultOut[] = data?.items ?? []
  const total = data?.total ?? 0

  const tabItems = [
    { key: 'all',            label: <span>全部 <Badge count={counts.all} showZero style={{ backgroundColor: '#8c8c8c' }} /></span> },
    { key: 'pending_review', label: <span>待复核·自动匹配 <Badge count={counts.pending_review} showZero style={{ backgroundColor: '#fa8c16' }} /></span> },
    { key: 'confirmed',      label: <span>已人工确认 <Badge count={counts.confirmed} showZero style={{ backgroundColor: '#1677ff' }} /></span> },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Row gutter={[12, 12]} align="middle">
          <Col>
            <Space>
              <Text type="secondary">任务：</Text>
              <Select
                allowClear showSearch style={{ width: 260 }}
                placeholder="全部任务（未选时展示全库）"
                value={state.cleanJobId}
                options={jobOptions}
                optionFilterProp="label"
                onChange={v => setState({ cleanJobId: v ?? undefined })}
              />
            </Space>
          </Col>
          <Col>
            <Space>
              <Text type="secondary">来源：</Text>
              <Select
                mode="multiple" allowClear style={{ width: 320 }}
                placeholder="匹配来源（多选）"
                value={state.matchSource}
                options={MATCH_SOURCE_OPTIONS}
                onChange={v => setState({ matchSource: v })}
              />
            </Space>
          </Col>
          <Col>
            <Space>
              <Text type="secondary">价格预警：</Text>
              <Select
                allowClear style={{ width: 140 }}
                placeholder="预警"
                value={state.priceFlag}
                options={PRICE_FLAG_OPTIONS}
                onChange={v => setState({ priceFlag: v ?? undefined })}
              />
            </Space>
          </Col>
          <Col flex="auto">
            <Input.Search
              allowClear
              placeholder="按商品名称搜索"
              value={keywordInput}
              onChange={e => setKeywordInput(e.target.value)}
              onSearch={v => setState({ keyword: v })}
              style={{ maxWidth: 320 }}
            />
          </Col>
          <Col>
            <Space>
              <Button onClick={reset}>重置</Button>
              <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
            </Space>
          </Col>
        </Row>
        {!state.cleanJobId && (
          <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
            未选任务时展示全库最新结果（按 ID 倒序，最多 20 条/页）
          </Text>
        )}
      </Card>

      <Card>
        <Tabs
          activeKey={state.tab}
          items={tabItems}
          onChange={k => setState({ tab: k as MatchResultsTab })}
        />
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={items}
          scroll={{ x: 1280 }}
          pagination={{
            current: state.page,
            pageSize: 20,
            total,
            onChange: p => setState({ page: p }),
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>

      <ReselectModal
        open={reselectOpen}
        matchId={reselectMatchId}
        onClose={() => { setReselectOpen(false); setReselectMatchId(null) }}
        onSuccess={() => refresh()}
      />
    </Space>
  )
}
