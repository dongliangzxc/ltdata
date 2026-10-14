import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert, Button, Card, Divider, Input, Radio, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import CreateBrandModal from '../../components/CreateBrandModal'
import {
  listBrands, listCleanJobBrandRows, updateCleanJobBrandRows,
} from '../../services/api'
import type { BrandCleanRow, BrandItem } from '../../services/api'

const { Text, Title } = Typography

type BrandOption = { value: string; label: string }

const formatText = (value?: string | number | null) => (value === null || value === undefined || value === '' ? '-' : String(value))

export default function BrandCleanPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = Number(searchParams.get('clean_job_id') || '')

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [actionableOnly, setActionableOnly] = useState(true)
  const [draft, setDraft] = useState<Record<number, string | null | undefined>>({})
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchBrand, setBatchBrand] = useState<string | undefined>(undefined)
  const [saving, setSaving] = useState(false)
  const [brandOptions, setBrandOptions] = useState<BrandOption[]>([])
  const [brandModalOpen, setBrandModalOpen] = useState(false)
  const [brandTargetRowId, setBrandTargetRowId] = useState<number | null>(null)

  useEffect(() => {
    listBrands({ page: 1, page_size: 2000 })
      .then(r => {
        setBrandOptions((r.data.items ?? []).map(b => ({
          value: b.brand_code,
          label: b.brand_name ? `${b.brand_name}（${b.brand_code}）` : b.brand_code,
        })))
      })
      .catch(() => {})
  }, [])

  const { data, loading, refresh } = useRequest(
    () => listCleanJobBrandRows(jobId, {
      page,
      page_size: pageSize,
      keyword: keyword || undefined,
      actionable_only: actionableOnly,
    }).then(r => r.data),
    { ready: Number.isFinite(jobId) && jobId > 0, refreshDeps: [jobId, page, pageSize, keyword, actionableOnly] },
  )

  const rows = useMemo(() => data?.items ?? [], [data])

  useEffect(() => {
    setDraft({})
    setSelectedIds([])
    setBatchBrand(undefined)
  }, [page, pageSize, keyword, actionableOnly, jobId])

  const originalValue = (row: BrandCleanRow): string | null => {
    if (row.brand_std_manual) return row.brand_std ?? null
    if (row.has_model) return row.model_brand_code ?? null
    return row.brand_std ?? null
  }

  const rowValue = (row: BrandCleanRow): string | undefined => {
    if (draft[row.cleaned_data_id] !== undefined) return draft[row.cleaned_data_id] ?? undefined
    return originalValue(row) ?? undefined
  }

  const changedItems = useMemo(
    () => rows
      .filter(row => draft[row.cleaned_data_id] !== undefined)
      .filter(row => (draft[row.cleaned_data_id] ?? null) !== originalValue(row))
      .map(row => ({ cleaned_data_id: row.cleaned_data_id, brand_std: draft[row.cleaned_data_id] ?? null })),
    [rows, draft],
  )

  const handleSet = (row: BrandCleanRow, value: string | undefined) => {
    setDraft(prev => ({ ...prev, [row.cleaned_data_id]: value ?? null }))
  }

  const openCreateBrand = (rowId?: number) => {
    setBrandTargetRowId(rowId ?? null)
    setBrandModalOpen(true)
  }

  const renderBrandDropdown = (rowId?: number) => (menu: ReactElement) => (
    <>
      {menu}
      <Divider style={{ margin: '4px 0' }} />
      <Button
        type="link"
        icon={<PlusOutlined />}
        style={{ width: '100%', textAlign: 'left' }}
        onClick={() => openCreateBrand(rowId)}
      >
        新建品牌
      </Button>
    </>
  )

  const handleBatchApply = () => {
    const chosenBrand = batchBrand
    if (chosenBrand === undefined) {
      message.warning('请先选择要设置的品牌')
      return
    }
    if (selectedIds.length === 0) {
      message.warning('请先勾选要处理的数据行')
      return
    }
    setDraft(prev => {
      const next = { ...prev }
      selectedIds.forEach(id => { next[id] = chosenBrand })
      return next
    })
    message.success(`已为 ${selectedIds.length} 行设置品牌，记得点击保存`)
  }

  const handleCreatedBrand = (brand: BrandItem) => {
    setBrandOptions(prev => {
      if (prev.some(o => o.value === brand.brand_code)) return prev
      return [...prev, {
        value: brand.brand_code,
        label: brand.brand_name ? `${brand.brand_name}（${brand.brand_code}）` : brand.brand_code,
      }].sort((a, b) => a.value.localeCompare(b.value))
    })
    if (brandTargetRowId != null) {
      setDraft(prev => ({ ...prev, [brandTargetRowId]: brand.brand_code }))
      message.success('品牌已创建并设为该行品牌，记得点击保存')
    } else if (selectedIds.length > 0) {
      setDraft(prev => {
        const next = { ...prev }
        selectedIds.forEach(id => { next[id] = brand.brand_code })
        return next
      })
      message.success(`品牌已创建，已为选中的 ${selectedIds.length} 行设置，记得点击保存`)
    } else {
      setBatchBrand(brand.brand_code)
      message.success('品牌已创建，可在「批量设置品牌」中选择并应用')
    }
    setBrandModalOpen(false)
    setBrandTargetRowId(null)
  }

  const handleSave = async () => {
    if (changedItems.length === 0) {
      message.info('没有需要保存的修改')
      return
    }
    setSaving(true)
    try {
      const res = await updateCleanJobBrandRows(jobId, changedItems)
      message.success(`已保存 ${res.data.updated} 条`)
      setDraft({})
      setSelectedIds([])
      setBatchBrand(undefined)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  if (!Number.isFinite(jobId) || jobId <= 0) {
    return (
      <Card>
        <Alert type="error" showIcon message="缺少 clean_job_id 参数，请从清洗任务列表进入本页。" />
      </Card>
    )
  }

  const columns: ColumnsType<BrandCleanRow> = [
    { title: '平台', dataIndex: 'platform', width: 90, render: formatText },
    { title: '商品名称', dataIndex: 'item_name', ellipsis: true, render: formatText },
    { title: '原品牌', dataIndex: 'brand_raw', width: 140, ellipsis: true, render: formatText },
    {
      title: '当前入库品牌', dataIndex: 'brand_std', width: 160,
      render: (_: unknown, row) => {
        if (row.has_model && !row.brand_std_manual) {
          return <Tag color="blue">{formatText(row.model_brand_code)}{row.model_brand_name ? ` ${row.model_brand_name}` : ''}</Tag>
        }
        return formatText(row.brand_std)
      },
    },
    {
      title: '品牌设置', width: 240,
      render: (_: unknown, row) => (
        <Select
          showSearch
          allowClear
          style={{ width: '100%' }}
          placeholder="选择品牌"
          options={brandOptions}
          value={rowValue(row)}
          popupRender={renderBrandDropdown(row.cleaned_data_id)}
          filterOption={(input, option) => (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
          onChange={(value: string | undefined) => handleSet(row, value)}
        />
      ),
    },
    {
      title: '说明', width: 220,
      render: (_: unknown, row) => (
        <Space size={4} wrap>
          {row.brand_identified === 0 && !row.has_model && <Tag color="purple">未识别品牌</Tag>}
          {row.has_model
            ? <Text type="secondary">已匹配型号，可人工覆盖品牌</Text>
            : <Text type="secondary">未匹配型号，可人工补充品牌</Text>}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space align="center" style={{ marginBottom: 12 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/clean')}>返回清洗任务</Button>
          <Title level={5} style={{ margin: 0 }}>只清洗品牌（任务 #{jobId}）</Title>
        </Space>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="在此补充「入库品牌」，保存后只更新该行的入库品牌字段（品牌码）；人工设置的品牌在详情/导出中优先于型号品牌。不会写入型号匹配结果，任务也不会因此标记为「清洗完成」。默认显示待处理（待确认 / URL映射待确认 / 争议）行，可在「全部数据行」中查看其它行。"
        />
        <Space wrap style={{ marginBottom: 12 }}>
          <Radio.Group
            value={actionableOnly}
            onChange={e => { setActionableOnly(e.target.value); setPage(1) }}
            optionType="button"
            buttonStyle="solid"
            options={[
              { label: '待处理（待确认 / URL映射待确认 / 争议）', value: true },
              { label: '全部数据行', value: false },
            ]}
          />
          <Input.Search
            allowClear
            placeholder="按商品名称搜索"
            style={{ width: 260 }}
            value={keywordInput}
            onChange={e => setKeywordInput(e.target.value)}
            onSearch={value => { setKeyword(value.trim()); setPage(1) }}
          />
          <Select
            showSearch
            allowClear
            placeholder="批量设置品牌"
            style={{ width: 260 }}
            options={brandOptions}
            value={batchBrand}
            popupRender={renderBrandDropdown()}
            filterOption={(input, option) => (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
            onChange={(value: string | undefined) => setBatchBrand(value)}
          />
          <Button icon={<PlusOutlined />} onClick={() => openCreateBrand()}>新建品牌</Button>
          <Button onClick={handleBatchApply} disabled={selectedIds.length === 0}>批量设置选中（{selectedIds.length}）</Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={changedItems.length === 0}
            onClick={handleSave}
          >
            保存修改（{changedItems.length}）
          </Button>
        </Space>
        <Table
          dataSource={rows}
          columns={columns}
          rowKey="cleaned_data_id"
          size="small"
          loading={loading}
          scroll={{ x: 1000 }}
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: keys => setSelectedIds(keys as number[]),
          }}
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100'],
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>
      <CreateBrandModal
        open={brandModalOpen}
        onCancel={() => { setBrandModalOpen(false); setBrandTargetRowId(null) }}
        onCreated={handleCreatedBrand}
      />
    </Space>
  )
}
