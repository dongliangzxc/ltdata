import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert, Button, Card, Divider, Input, Popconfirm, Radio, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeftOutlined, DownloadOutlined, PlusOutlined, SaveOutlined, StopOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import CreateBrandModal from '../../components/CreateBrandModal'
import ProgressModal from '../../components/ProgressModal'
import {
  excludeCleanJobBrandRows, getDownloadUrl, getExportJob, listBrands,
  listCleanJobBrandRows, triggerExport, updateCleanJobBrandRows,
} from '../../services/api'
import type { BrandCleanGroup, BrandCleanRow, BrandCleanSearchBy, BrandItem } from '../../services/api'

const { Text, Title } = Typography

type BrandOption = { value: string; label: string }

const formatText = (value?: string | number | null) => (value === null || value === undefined || value === '' ? '-' : String(value))

const GROUP_OPTIONS: { label: string; value: BrandCleanGroup }[] = [
  { label: '待处理', value: 'actionable' },
  { label: '未识别品牌', value: 'unidentified_brand' },
  { label: '待确认', value: 'pending' },
  { label: 'URL映射待确认', value: 'text_only' },
  { label: '争议复核', value: 'disputed' },
  { label: '全部数据行', value: 'all' },
]

const SEARCH_OPTIONS: { label: string; value: BrandCleanSearchBy }[] = [
  { label: '宝贝名称', value: 'item_name' },
  { label: '原品牌', value: 'brand_raw' },
  { label: '入库品牌', value: 'brand_code' },
  { label: '店铺', value: 'shop_name' },
  { label: '型号', value: 'model_code' },
]

const SEARCH_PLACEHOLDER: Record<BrandCleanSearchBy, string> = {
  item_name: '搜索宝贝名称',
  brand_raw: '搜索原品牌',
  brand_code: '搜索入库品牌',
  shop_name: '搜索店铺',
  model_code: '搜索型号',
}

const SORT_OPTIONS = [
  { value: 'default', label: '默认排序' },
  { value: 'item_name_asc', label: '名称 A→Z' },
  { value: 'item_name_desc', label: '名称 Z→A' },
  { value: 'sales_qty_desc', label: '销量从高到低' },
  { value: 'sales_qty_asc', label: '销量从低到高' },
  { value: 'price_desc', label: '价格从高到低' },
  { value: 'price_asc', label: '价格从低到高' },
]

export default function BrandCleanPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = Number(searchParams.get('clean_job_id') || '')

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [searchBy, setSearchBy] = useState<BrandCleanSearchBy>('item_name')
  const [sortBy, setSortBy] = useState('default')
  const [group, setGroup] = useState<BrandCleanGroup>('actionable')
  const [draft, setDraft] = useState<Record<number, string | null | undefined>>({})
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchBrand, setBatchBrand] = useState<string | undefined>(undefined)
  const [saving, setSaving] = useState(false)
  const [excluding, setExcluding] = useState(false)
  const [brandOptions, setBrandOptions] = useState<BrandOption[]>([])
  const [brandSearchOptions, setBrandSearchOptions] = useState<BrandOption[]>([])
  const [brandSearchKeyword, setBrandSearchKeyword] = useState('')
  const [brandSearchLoading, setBrandSearchLoading] = useState(false)
  const [brandModalOpen, setBrandModalOpen] = useState(false)
  const [brandTargetRowId, setBrandTargetRowId] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportProgress, setExportProgress] = useState(0)
  const [exportError, setExportError] = useState('')
  const [exportProgressVisible, setExportProgressVisible] = useState(false)
  const exportPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const brandSearchSeqRef = useRef(0)

  useEffect(() => {
    return () => {
      if (exportPollRef.current) clearInterval(exportPollRef.current)
    }
  }, [])

  const toBrandOption = (brand: BrandItem): BrandOption => ({
    value: brand.brand_code,
    label: brand.brand_name ? `${brand.brand_name}（${brand.brand_code}）` : brand.brand_code,
  })

  const loadBrandOptions = async (keyword?: string) => {
    const kw = keyword?.trim() || ''
    const seq = ++brandSearchSeqRef.current
    setBrandSearchLoading(true)
    try {
      const res = await listBrands({ keyword: kw || undefined, page: 1, page_size: kw ? 50 : 2000 })
      if (seq !== brandSearchSeqRef.current) return
      const options = (res.data.items ?? []).map(toBrandOption)
      if (kw) {
        setBrandSearchKeyword(kw)
        setBrandSearchOptions(options)
      } else {
        setBrandSearchKeyword('')
        setBrandSearchOptions([])
        setBrandOptions(options)
      }
    } catch {
      // keep the previous options on failure
    } finally {
      if (seq === brandSearchSeqRef.current) setBrandSearchLoading(false)
    }
  }

  useEffect(() => {
    loadBrandOptions()
  }, [])

  const resetBrandSearch = () => {
    brandSearchSeqRef.current += 1
    setBrandSearchKeyword('')
    setBrandSearchOptions([])
    setBrandSearchLoading(false)
  }

  const brandSelectOptions = brandSearchKeyword ? brandSearchOptions : brandOptions

  const rememberBrandOption = (value?: string) => {
    if (!value) return
    const option = brandSelectOptions.find(o => o.value === value)
    if (!option) return
    setBrandOptions(prev => (
      prev.some(o => o.value === value)
        ? prev
        : [...prev, option].sort((a, b) => a.value.localeCompare(b.value))
    ))
  }

  const { data, loading, refresh } = useRequest(
    () => listCleanJobBrandRows(jobId, {
      page,
      page_size: pageSize,
      keyword: keyword || undefined,
      search_by: searchBy,
      group,
      sort_by: sortBy,
    }).then(r => r.data),
    { ready: Number.isFinite(jobId) && jobId > 0, refreshDeps: [jobId, page, pageSize, keyword, searchBy, group, sortBy] },
  )

  const rows = useMemo(() => data?.items ?? [], [data])

  useEffect(() => {
    setDraft({})
    setSelectedIds([])
    setBatchBrand(undefined)
  }, [page, pageSize, keyword, searchBy, group, sortBy, jobId])

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
    rememberBrandOption(value)
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
    const createdOption = toBrandOption(brand)
    const mergeOption = (prev: BrandOption[]) => (
      prev.some(o => o.value === createdOption.value)
        ? prev
        : [...prev, createdOption].sort((a, b) => a.value.localeCompare(b.value))
    )
    setBrandOptions(mergeOption)
    setBrandSearchOptions(mergeOption)
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

  const handleExclude = async (cleanedDataIds: number[]) => {
    if (cleanedDataIds.length === 0) return
    setExcluding(true)
    try {
      const res = await excludeCleanJobBrandRows(jobId, cleanedDataIds)
      message.success(`已排除 ${res.data.excluded} 条`)
      setSelectedIds([])
      setDraft({})
      refresh()
    } finally {
      setExcluding(false)
    }
  }

  const handleExport = async () => {
    if (exportPollRef.current) return
    setExporting(true)
    setExportProgress(0)
    setExportError('')
    setExportProgressVisible(true)
    try {
      const res = await triggerExport({ clean_job_id: jobId, filename_prefix: '品牌清洗' })
      const { job_id } = res.data as { job_id: number }
      let pollFailCount = 0
      exportPollRef.current = setInterval(async () => {
        try {
          const jobRes = await getExportJob(job_id)
          const job = jobRes.data as { status: string; token?: string | null; error_msg?: string | null }
          pollFailCount = 0
          if (job.status === 'running') setExportProgress(50)
          if (job.status === 'done' && job.token) {
            if (exportPollRef.current) { clearInterval(exportPollRef.current); exportPollRef.current = null }
            setExportProgress(100)
            setTimeout(() => {
              setExportProgressVisible(false)
              setExporting(false)
              const a = document.createElement('a')
              a.href = getDownloadUrl(job.token!)
              a.click()
            }, 800)
          } else if (job.status === 'error') {
            if (exportPollRef.current) { clearInterval(exportPollRef.current); exportPollRef.current = null }
            setExportError(job.error_msg || '导出失败，请重试')
            setExporting(false)
          }
        } catch {
          pollFailCount++
          if (pollFailCount >= 10) {
            if (exportPollRef.current) { clearInterval(exportPollRef.current); exportPollRef.current = null }
            setExportError('网络异常，请刷新后重试')
            setExporting(false)
          }
        }
      }, 1000)
    } catch {
      setExportProgressVisible(false)
      setExporting(false)
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
    { title: '销量', dataIndex: 'sales_qty', width: 90, render: (v: number | null) => (v ?? '-') },
    { title: '原品牌', dataIndex: 'brand_raw', width: 140, ellipsis: true, render: formatText },
    {
      title: '当前入库品牌', dataIndex: 'brand_std', width: 200,
      render: (_: unknown, row) => (
        <Space size={4} wrap>
          {row.has_model && !row.brand_std_manual
            ? <Tag color="blue">{formatText(row.model_brand_code)}{row.model_brand_name ? ` ${row.model_brand_name}` : ''}</Tag>
            : formatText(row.brand_std)}
          {row.brand_std_manual && <Tag color="green">品牌已确认</Tag>}
        </Space>
      ),
    },
    {
      title: '品牌设置', width: 240,
      render: (_: unknown, row) => (
        <Select
          showSearch
          allowClear
          style={{ width: '100%' }}
          placeholder="选择品牌"
          options={brandSelectOptions}
          value={rowValue(row)}
          disabled={!row.editable}
          popupRender={renderBrandDropdown(row.cleaned_data_id)}
          notFoundContent={brandSearchLoading ? '搜索中...' : undefined}
          filterOption={false}
          onSearch={loadBrandOptions}
          onOpenChange={open => { if (!open) resetBrandSearch() }}
          onChange={(value: string | undefined) => handleSet(row, value)}
        />
      ),
    },
    {
      title: '说明', width: 220,
      render: (_: unknown, row) => (
        <Space size={4} wrap>
          {row.brand_identified === 0 && !row.has_model && <Tag color="purple">未识别品牌</Tag>}
          {!row.editable
            ? <Text type="secondary">已匹配/已确认/已排除，不可修改</Text>
            : row.has_model
              ? <Text type="secondary">已匹配型号，可人工覆盖品牌</Text>
              : <Text type="secondary">未匹配型号，可人工补充品牌</Text>}
        </Space>
      ),
    },
    {
      title: '操作', width: 90, fixed: 'right',
      render: (_: unknown, row) => (
        row.editable ? (
          <Popconfirm
            title="确认排除该行？"
            okText="排除"
            cancelText="取消"
            onConfirm={() => handleExclude([row.cleaned_data_id])}
          >
            <Button type="link" danger size="small" icon={<StopOutlined />}>排除</Button>
          </Popconfirm>
        ) : <Text type="secondary">-</Text>
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
            value={group}
            onChange={e => { setGroup(e.target.value); setPage(1) }}
            optionType="button"
            buttonStyle="solid"
            options={GROUP_OPTIONS}
          />
          <Select
            value={searchBy}
            style={{ width: 110 }}
            options={SEARCH_OPTIONS}
            onChange={v => { setSearchBy(v); setKeyword(''); setKeywordInput(''); setPage(1) }}
          />
          <Input.Search
            allowClear
            placeholder={SEARCH_PLACEHOLDER[searchBy]}
            style={{ width: 200 }}
            value={keywordInput}
            onChange={e => setKeywordInput(e.target.value)}
            onSearch={value => { setKeyword(value.trim()); setPage(1) }}
          />
          <Select
            value={sortBy}
            style={{ width: 150 }}
            options={SORT_OPTIONS}
            onChange={v => { setSortBy(v); setPage(1) }}
          />
          <Select
            showSearch
            allowClear
            placeholder="批量设置品牌"
            style={{ width: 260 }}
            options={brandSelectOptions}
            value={batchBrand}
            popupRender={renderBrandDropdown()}
            notFoundContent={brandSearchLoading ? '搜索中...' : undefined}
            filterOption={false}
            onSearch={loadBrandOptions}
            onOpenChange={open => { if (!open) resetBrandSearch() }}
            onChange={(value: string | undefined) => { setBatchBrand(value); rememberBrandOption(value) }}
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
          <Button
            danger
            icon={<StopOutlined />}
            loading={excluding}
            disabled={selectedIds.length === 0}
            onClick={() => handleExclude(selectedIds)}
          >
            一键排除选中（{selectedIds.length}）
          </Button>
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>导出全部数据</Button>
        </Space>
        <Table
          dataSource={rows}
          columns={columns}
          rowKey="cleaned_data_id"
          size="small"
          loading={loading}
          scroll={{ x: 1280 }}
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: keys => setSelectedIds(keys as number[]),
            getCheckboxProps: (row: BrandCleanRow) => ({ disabled: !row.editable }),
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
      <ProgressModal
        visible={exportProgressVisible}
        title="正在导出全部数据..."
        progress={exportProgress}
        errorMsg={exportError}
      />
    </Space>
  )
}
