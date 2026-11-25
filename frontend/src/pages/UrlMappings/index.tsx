import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card, Table, Button, Input, Select, Space, Typography,
  Modal, Form, InputNumber, message, Popconfirm, Tag, Alert, Checkbox, DatePicker,
} from 'antd'
import type { Dayjs } from 'dayjs'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUrlMappings, createUrlMapping, updateUrlMapping,
  deleteUrlMapping, listModels, getModelDetail, downloadUrlMappingTemplate,
  listModelExtraFields, getUrlMappingCategoryCount, bulkDeleteUrlMappings, bulkSetUrlMappingsEnabled,
} from '../../services/api'
import type { UserProfile, UrlMappingDeleteScope } from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
import ImportMappingModal from '../../components/ImportMappingModal'
import { formatModelLabel } from '../../utils/modelLabel'
import { buildUrlMappingFilters, describeUrlMappingFilters, buildUrlMappingDeleteScope, countSelectedUrlMappings, isUrlMappingSelected, selectUrlMappingRows } from './filters'
import type { UrlMappingSelection } from './filters'

const { Text } = Typography

function readStoredUser(): UserProfile | null {
  if (typeof localStorage === 'undefined') return null
  const raw = localStorage.getItem('auth_user')
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserProfile
  } catch {
    return null
  }
}

type UrlMapping = {
  id: number
  platform: string
  item_id: string
  item_url: string | null
  model_id: number
  price: number | null
  brand_code: string | null
  model_code: string | null
  brand_name: string | null
  model_name: string | null
  series: string | null
  category_code: string | null
  category_name: string | null
  item_name: string | null
  source: string | null
  data_year: number | null
  data_month: number | null
  is_enabled: boolean
  operator: string | null
  updated_at: string | null
}

type ModelOption = {
  id: number
  brand_code: string
  model_code: string | null
  brand_name: string | null
  model_name: string | null
  series: string | null
  category_code: string | null
}

const PLATFORM_OPTIONS = [
  { value: 'jd', label: '京东 (JD)' },
  { value: 'tmall', label: '天猫 (TMALL)' },
  { value: 'taobao', label: '淘宝 (TAOBAO)' },
  { value: 'douyin', label: '抖音 (DOUYIN)' },
  { value: 'suning', label: '苏宁 (SUNING)' },
  { value: 'amazon', label: '亚马逊 (AMAZON)' },
  { value: 'shopee', label: '虾皮 (SHOPEE)' },
]

export default function UrlMappingsPage() {
  const [keyword, setKeyword] = useState('')
  const [platform, setPlatform] = useState<string | undefined>()
  const [brand, setBrand] = useState('')
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [modalCategoryCode, setModalCategoryCode] = useState<string | undefined>()
  const [modalSeries, setModalSeries] = useState<string | undefined>()
  const [editModelOption, setEditModelOption] = useState<ModelOption | null>(null)

  const [filterMonths, setFilterMonths] = useState<[Dayjs, Dayjs] | null>(null)
  const [filterEnabled, setFilterEnabled] = useState<boolean | undefined>()
  const [statusUpdating, setStatusUpdating] = useState<boolean | null>(null)

  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkCount, setBulkCount] = useState<number | null>(null)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [bulkFilters, setBulkFilters] = useState<UrlMappingDeleteScope | null>(null)
  const bulkCountSeqRef = useRef(0)
  const mappingFilters = useMemo(() => categoryCode ? buildUrlMappingFilters({
    category_code: categoryCode, platform, brand, keyword,
    start_month: filterMonths ? Number(filterMonths[0].format('YYYYMM')) : undefined,
    end_month: filterMonths ? Number(filterMonths[1].format('YYYYMM')) : undefined,
    enabled: filterEnabled,
  }) : null, [categoryCode, platform, brand, keyword, filterMonths, filterEnabled])
  const filterKey = JSON.stringify(mappingFilters)
  const [selectionState, setSelectionState] = useState<{ scope: string; selection: UrlMappingSelection }>({
    scope: filterKey, selection: { all: true, ids: [] },
  })
  const selection: UrlMappingSelection = selectionState.scope === filterKey
    ? selectionState.selection : { all: true, ids: [] }
  const updateSelection = (next: UrlMappingSelection) => setSelectionState({ scope: filterKey, selection: next })
  useEffect(() => {
    setSelectionState({ scope: filterKey, selection: { all: true, ids: [] } })
  }, [filterKey])

  const currentUser = readStoredUser()
  const { options: categoryOptions } = useCategoryOptions()
  const visibleCategoryOptions = useMemo(() => {
    if (!currentUser) return categoryOptions
    if (currentUser.is_admin === 1) return categoryOptions
    if (!currentUser.category_permissions?.length) return categoryOptions
    const allowed = new Set(currentUser.category_permissions)
    return categoryOptions.filter(c => allowed.has(c.value))
  }, [categoryOptions, currentUser])
  const visibleCategoryCodes = useMemo(() => new Set(visibleCategoryOptions.map(c => c.value)), [visibleCategoryOptions])

  const { data: extraFieldsData } = useRequest(() => listModelExtraFields().then(r => r.data))
  const extraFieldKeysByCategory = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const f of extraFieldsData ?? []) {
      if (!map[f.category_code]) map[f.category_code] = []
      map[f.category_code].push(f.field_key)
    }
    return map
  }, [extraFieldsData])
  const showSeriesColumn = useMemo(() => {
    if (!categoryCode) return false
    return (extraFieldKeysByCategory[categoryCode] ?? []).includes('series')
  }, [categoryCode, extraFieldKeysByCategory])

  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 500 }).then(r => r.data)
  )
  const modelOptions: ModelOption[] = (modelsData?.items ?? []).map(m => ({
    id: m.id,
    brand_code: m.brand_code,
    model_code: m.model_code,
    brand_name: m.brand_name ?? null,
    model_name: m.model_name ?? null,
    series: m.series ?? null,
    category_code: m.category_code ?? null,
  }))
  const visibleModelOptions = modelOptions.filter(m => !m.category_code || visibleCategoryCodes.has(m.category_code))

  const { data, loading, refresh } = useRequest(
    () => {
      if (!mappingFilters) {
        return Promise.resolve({ items: [] as UrlMapping[], total: 0, page: 1, page_size: 20 })
      }
      return listUrlMappings({
        ...mappingFilters,
        require_category: true,
        page,
        page_size: 20,
      }).then(r => r.data)
    },
    { refreshDeps: [mappingFilters, page] }
  )
  const selectedCount = countSelectedUrlMappings(selection, data?.total ?? 0)
  const selectedRowKeys = (data?.items ?? [])
    .filter((row: UrlMapping) => isUrlMappingSelected(selection, row.id))
    .map((row: UrlMapping) => row.id)

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    setModalCategoryCode(undefined)
    setModalSeries(undefined)
    setModalOpen(true)
  }

  const openEdit = (record: UrlMapping) => {
    setEditingId(record.id)
    form.setFieldsValue({
      platform: record.platform,
      item_id: record.item_id,
      item_url: record.item_url,
      model_id: record.model_id,
      price: record.price,
      data_year: record.data_year,
      data_month: record.data_month,
    })
    setModalCategoryCode(record.category_code ?? undefined)
    setModalSeries(record.series ?? undefined)
    setEditModelOption(null)
    if (record.model_id != null) {
      getModelDetail(record.model_id)
        .then(res => {
          const m = res.data
          setEditModelOption({
            id: m.id,
            brand_code: m.brand_code,
            model_code: m.model_code,
            brand_name: m.brand_name ?? null,
            model_name: m.model_name ?? null,
            series: m.series ?? null,
            category_code: m.category_code ?? null,
          })
        })
        .catch(() => {})
    }
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editingId) {
        await updateUrlMapping(editingId, values)
        message.success('已更新')
      } else {
        await createUrlMapping(values)
        message.success('已新增')
      }
      setModalOpen(false)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    await deleteUrlMapping(id)
    message.success('已删除')
    setSelectionState(prev => prev.scope === filterKey
      ? { ...prev, selection: { ...prev.selection, ids: prev.selection.ids.filter(value => value !== id) } }
      : prev)
    refresh()
  }

  const handleBulkStatus = async (enabled: boolean) => {
    if (!mappingFilters || !selectedCount || loading || statusUpdating != null) return
    const scope = buildUrlMappingDeleteScope(mappingFilters, selection)
    setStatusUpdating(enabled)
    try {
      const res = await bulkSetUrlMappingsEnabled(scope, enabled)
      message.success(`已${enabled ? '启用' : '禁用'} ${res.data.updated} 条映射（所选共 ${res.data.matched} 条）`)
      updateSelection({ all: false, ids: [] })
      setPage(1)
      refresh()
    } catch {
      // API interceptor displays the error; retain the selection for retry.
    } finally {
      setStatusUpdating(null)
    }
  }

  const bulkFilterDescription = bulkFilters ? describeUrlMappingFilters(
    bulkFilters,
    visibleCategoryOptions.find(o => o.value === bulkFilters.category_code)?.label,
    PLATFORM_OPTIONS.find(o => o.value === bulkFilters.platform)?.label,
  ) : []

  const closeBulkDelete = () => {
    if (bulkDeleting) return
    bulkCountSeqRef.current += 1
    setBulkOpen(false)
    setBulkFilters(null)
    setBulkCount(null)
  }

  const openBulkDelete = async () => {
    if (!mappingFilters || !selectedCount) return
    const filters = buildUrlMappingDeleteScope(mappingFilters, selection)
    const seq = ++bulkCountSeqRef.current
    setBulkFilters(filters)
    setBulkOpen(true)
    setBulkCount(null)
    setBulkLoading(true)
    try {
      const res = await getUrlMappingCategoryCount(filters)
      if (seq !== bulkCountSeqRef.current) return
      setBulkCount(res.data.count)
    } catch {
      if (seq !== bulkCountSeqRef.current) return
      message.error('获取待删除数量失败，请重试')
    } finally {
      if (seq === bulkCountSeqRef.current) setBulkLoading(false)
    }
  }

  const handleBulkDelete = async () => {
    if (!bulkFilters || bulkLoading || bulkCount == null || bulkCount <= 0 || bulkDeleting) return
    setBulkDeleting(true)
    try {
      const res = await bulkDeleteUrlMappings(bulkFilters, bulkCount)
      message.success(`已删除 ${res.data.deleted} 条映射`)
      setBulkOpen(false)
      setBulkFilters(null)
      setBulkCount(null)
      updateSelection({ all: false, ids: [] })
      setPage(1)
      refresh()
    } catch {
      // handled by interceptor; keep the preview open so the user can retry or close it
    } finally {
      setBulkDeleting(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      const res = await downloadUrlMappingTemplate()
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const a = document.createElement('a')
      document.body.appendChild(a)
      a.href = url
      a.download = 'URL映射导入模板.xlsx'
      a.click()
      document.body.removeChild(a)
      setTimeout(() => window.URL.revokeObjectURL(url), 100)
    } catch {
      message.error('模板下载失败，请重试')
    }
  }

  const modalCategoryIsSeries = !!modalCategoryCode
    && (extraFieldKeysByCategory[modalCategoryCode] ?? []).includes('series')

  const modalSeriesOptions = useMemo(() => {
    if (!modalCategoryIsSeries || !modalCategoryCode) return []
    const values = new Set<string>()
    for (const m of visibleModelOptions) {
      if (m.category_code === modalCategoryCode && m.series) values.add(m.series)
    }
    if (editModelOption?.series && editModelOption.category_code === modalCategoryCode) {
      values.add(editModelOption.series)
    }
    return Array.from(values).sort()
  }, [modalCategoryIsSeries, modalCategoryCode, visibleModelOptions, editModelOption])

  const filteredModelOptions = useMemo(() => {
    let base = modalCategoryCode
      ? visibleModelOptions.filter(m => m.category_code === modalCategoryCode)
      : visibleModelOptions
    if (modalSeries) base = base.filter(m => (m.series || '') === modalSeries)
    const seen = new Set(base.map(m => m.id))
    const extra: ModelOption[] = []
    if (editModelOption && !seen.has(editModelOption.id)) extra.push(editModelOption)
    return [...base, ...extra]
  }, [modalCategoryCode, modalSeries, visibleModelOptions, editModelOption])

  const columns = [
    {
      title: '状态', dataIndex: 'is_enabled', width: 90,
      render: (enabled: boolean) => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '已启用' : '已禁用'}</Tag>,
    },
    {
      title: '确认月份', width: 110,
      render: (_: unknown, record: UrlMapping) => record.data_year && record.data_month
        ? `${record.data_year}-${String(record.data_month).padStart(2, '0')}` : '未标注',
    },
    {
      title: '品类', width: 120,
      render: (_: unknown, record: UrlMapping) => record.category_name || record.category_code || '-'
    },
    {
      title: '品牌', width: 120,
      render: (_: unknown, record: UrlMapping) => record.brand_name || record.brand_code || '-'
    },
    {
      title: '商品ID / 链接', width: 180,
      render: (_: unknown, record: UrlMapping) => (
        <Space direction="vertical" size={0}>
          <Text type="secondary">{PLATFORM_OPTIONS.find(option => option.value === record.platform)?.label || record.platform}</Text>
          {record.item_url
            ? <a href={record.item_url} target="_blank" rel="noopener noreferrer">{record.item_id}</a>
            : <Text>{record.item_id}</Text>}
        </Space>
      ),
    },
    {
      title: '型号', dataIndex: 'model_code', width: 140,
      render: (v: string | null) => v ? <Text code>{v}</Text> : '-'
    },
    {
      title: '型号别名', dataIndex: 'model_name', width: 160,
      render: (v: string | null) => v || '-'
    },
    ...(showSeriesColumn ? [{
      title: '产品系列', dataIndex: 'series', width: 140, ellipsis: true,
      render: (v: string | null) => v || '-',
    }] : []),
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true, width: 240,
      render: (v: string | null) => v || '-'
    },
    {
      title: '判断类型',
      dataIndex: 'source',
      width: 110,
      render: (v: string | null) => {
        const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
          model_db_import: { label: '型号库导入', color: 'purple' },
          url_import:      { label: 'URL导入',   color: 'blue'   },
          match_confirm:   { label: '匹配确认',   color: 'green'  },
          manual:          { label: '手动创建',   color: 'orange' },
        }
        const cfg = v ? SOURCE_LABELS[v] : null
        return cfg
          ? <Tag color={cfg.color}>{cfg.label}</Tag>
          : <span style={{ color: '#ccc' }}>—</span>
      },
    },
    {
      title: '修改时间', dataIndex: 'updated_at', width: 150,
      render: (v: string | null) => v || '-'
    },
    {
      title: '操作人', dataIndex: 'operator', width: 90,
      render: (v: string | null) => v || '-'
    },
    {
      title: '操作', width: 120, fixed: 'right' as const,
      render: (_: unknown, record: UrlMapping) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space wrap>
          <DatePicker.RangePicker
            picker="month"
            placeholder={['确认开始月份', '确认结束月份']}
            value={filterMonths}
            onChange={dates => {
              setFilterMonths(dates?.[0] && dates?.[1] ? [dates[0], dates[1]] : null)
              setPage(1)
            }}
          />
          <Select
            placeholder="启用状态"
            value={filterEnabled == null ? undefined : Number(filterEnabled)}
            onChange={v => { setFilterEnabled(v == null ? undefined : Boolean(v)); setPage(1) }}
            allowClear
            style={{ width: 120 }}
            options={[{ value: 1, label: '已启用' }, { value: 0, label: '已禁用' }]}
          />
          <Select
            placeholder="品类筛选"
            allowClear
            style={{ width: 140 }}
            value={categoryCode}
            options={visibleCategoryOptions}
            onChange={v => { setCategoryCode(v); setPage(1) }}
          />
          <Select
            placeholder="平台筛选"
            allowClear
            style={{ width: 160 }}
            options={PLATFORM_OPTIONS}
            value={platform}
            onChange={v => { setPlatform(v); setPage(1) }}
          />
          <Input
            placeholder="品牌码 / 品牌名称"
            allowClear
            style={{ width: 180 }}
            value={brand}
            onChange={e => { setBrand(e.target.value); setPage(1) }}
          />
          <Input.Search
            placeholder="搜索 item_id / 型号 / 品牌"
            allowClear
            style={{ width: 280 }}
            onSearch={v => { setKeyword(v); setPage(1) }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>
          <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入 Excel</Button>
          <Button icon={<DownloadOutlined />} onClick={handleDownloadTemplate}>下载导入模板</Button>
          <Button
            disabled={!categoryCode || loading || selectedCount <= 0 || statusUpdating != null}
            loading={statusUpdating === true}
            onClick={() => handleBulkStatus(true)}
          >启用已选记录</Button>
          <Button
            disabled={!categoryCode || loading || selectedCount <= 0 || statusUpdating != null}
            loading={statusUpdating === false}
            onClick={() => handleBulkStatus(false)}
          >禁用已选记录</Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={!categoryCode || loading || selectedCount <= 0 || statusUpdating != null}
            title={categoryCode ? undefined : '请先选择品类'}
            onClick={openBulkDelete}
          >
            删除已选记录
          </Button>
        </Space>
      </Card>

      <Card>
        <Alert
          type="info"
          showIcon
          message="各品类可自行选择使用近 1 个月或近 3 个月等月份的链接"
          description="首次设置可先禁用品类全部链接，再按确认月份筛选并启用所需范围。操作覆盖跨页勾选记录；启用不会自动禁用其他月份。清洗只使用已启用的映射，已有结果和历史库规则保持原样。未标注月份的旧链接可编辑补充月份。"
          style={{ marginBottom: 16 }}
        />
        {!categoryCode ? (
          <Alert
            type="info"
            showIcon
            message="请先选择品类，再查看映射数据"
            description="映射数据量较大，选择品类后才会加载列表。"
          />
        ) : (
          <>
          <Space wrap style={{ marginBottom: 16 }}>
            <Checkbox
              checked={selection.all && selection.ids.length === 0}
              indeterminate={selectedCount > 0 && !(selection.all && selection.ids.length === 0)}
              disabled={loading || statusUpdating != null || !data?.total}
              onChange={e => updateSelection({ all: e.target.checked, ids: [] })}
            >
              全选筛选结果（跨页）
            </Checkbox>
            <Text>共 {data?.total ?? 0} 条，已选 {selectedCount} 条</Text>
            <Text type="secondary">默认全选，可取消勾选要保留的记录；更改筛选条件后重新全选。</Text>
          </Space>
          <Table
            dataSource={data?.items ?? []}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            rowSelection={{
              selectedRowKeys,
              getCheckboxProps: () => ({ disabled: loading || statusUpdating != null }),
              onSelect: (record, selected) => updateSelection(selectUrlMappingRows(selection, [record.id], selected)),
              onSelectAll: (selected, _rows, changedRows) => updateSelection(selectUrlMappingRows(selection, changedRows.map(row => row.id), selected)),
            }}
            scroll={{ x: showSeriesColumn ? 1810 : 1670 }}
            pagination={{
              current: page,
              pageSize: 20,
              total: data?.total ?? 0,
              onChange: setPage,
              showTotal: t => `共 ${t} 条`,
            }}
          />
          </>
        )}
      </Card>

      <ImportMappingModal
        open={importOpen}
        module="url"
        standardFields={[
          { value: 'platform', label: '平台', required: true },
          { value: 'item_url', label: '商品链接', required: true },
          { value: 'brand_code', label: '品牌码', required: true },
          { value: 'model_code', label: '型号码', required: true },
          { value: 'series', label: '产品系列' },
          { value: 'price', label: '价格' },
        ]}
        headersUrl="/url-mappings/headers"
        confirmUrl="/url-mappings/confirm"
        onSuccess={() => { refresh() }}
        onClose={() => setImportOpen(false)}
      />

      <Modal
        title="批量删除已选映射"
        open={bulkOpen}
        onCancel={closeBulkDelete}
        onOk={handleBulkDelete}
        okText="确认删除"
        cancelText="取消"
        okButtonProps={{ danger: true, disabled: bulkLoading || bulkCount == null || bulkCount <= 0 }}
        cancelButtonProps={{ disabled: bulkDeleting }}
        closable={!bulkDeleting}
        maskClosable={!bulkDeleting}
        keyboard={!bulkDeleting}
        confirmLoading={bulkDeleting}
        destroyOnClose
        width={480}
      >
        <Alert
          type="warning"
          showIcon
          message="该操作不可恢复，请谨慎执行"
          style={{ marginBottom: 12 }}
        />
        {bulkFilterDescription.map(([label, value]) => (
          <p key={label} style={{ marginBottom: 8 }}>{label}：<Text strong>{value}</Text></p>
        ))}
        <p style={{ marginBottom: 8 }}>
          选择方式：{bulkFilters?.include_ids != null
            ? `手动勾选 ${bulkFilters.include_ids.length} 条`
            : `全选筛选结果，取消勾选 ${bulkFilters?.exclude_ids?.length ?? 0} 条`}
        </p>
        <p style={{ marginBottom: 8 }}>
          将删除以上筛选范围中已勾选的 URL 映射记录（包含所有分页）
          {bulkLoading ? '（统计中…）' : bulkCount != null ? `，共 ${bulkCount} 条` : ''}。
        </p>
        <p style={{ color: '#999', marginBottom: 0 }}>
          仅删除映射链接，不删除型号或已有匹配结果。筛选结果数量变化时需重新确认。
        </p>
      </Modal>

      <Modal
        title={editingId ? '编辑映射' : '新增映射'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {/* 品类辅助筛选，不提交 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 4, fontSize: 14 }}>品类（筛选型号用）</div>
            <Select
              allowClear
              placeholder="选择品类可缩小型号列表"
              style={{ width: '100%' }}
              options={visibleCategoryOptions}
              value={modalCategoryCode}
              onChange={v => { setModalCategoryCode(v); setModalSeries(undefined) }}
            />
          </div>
          {modalCategoryIsSeries && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 4, fontSize: 14 }}>产品系列（筛选型号用）</div>
              <Select
                allowClear
                placeholder="选择产品系列可缩小型号列表"
                style={{ width: '100%' }}
                options={modalSeriesOptions.map(s => ({ value: s, label: s }))}
                value={modalSeries}
                onChange={v => setModalSeries(v)}
              />
            </div>
          )}
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={PLATFORM_OPTIONS} />
          </Form.Item>
          <Form.Item name="item_id" label="item_id" rules={[{ required: true }]}>
            <Input placeholder="如：100045223280" />
          </Form.Item>
          <Form.Item name="item_url" label="商品 URL">
            <Input placeholder="https://item.jd.com/..." />
          </Form.Item>
          <Form.Item name="model_id" label="型号" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder="搜索品牌/型号码"
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={filteredModelOptions.map(m => ({
                value: m.id,
                label: formatModelLabel(m),
              }))}
            />
          </Form.Item>
          <Form.Item name="price" label="单价（元）">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Space align="start">
            <Form.Item name="data_year" label="映射确认年份" rules={[{ required: true, message: '请填写确认年份' }]}>
              <InputNumber min={1} max={9999} precision={0} placeholder="如 2026" />
            </Form.Item>
            <Form.Item name="data_month" label="映射确认月份" rules={[{ required: true, message: '请选择确认月份' }]}>
              <Select style={{ width: 120 }} options={Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Space>
  )
}
