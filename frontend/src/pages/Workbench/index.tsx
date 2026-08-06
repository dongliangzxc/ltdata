import { useState, useEffect, useRef, useMemo } from 'react'
import {
  Card, Row, Col, Select, Input, Button, Table,
  Typography, Tooltip, Form, Statistic, Space,
  Popover, Spin, List, Checkbox, Modal
} from 'antd'
import { SearchOutlined, DownloadOutlined, ClearOutlined, LinkOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import {
  getWorkbenchFilters, queryWorkbenchData,
  getWorkbenchExportJob,
  exportWorkbench, fetchItemAttrs
} from '../../services/api'
import type { UserProfile } from '../../services/api'
import ProgressModal from '../../components/ProgressModal'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

const { Text } = Typography

type FilterOptions = {
  years: number[]
  months: number[]
  platforms: string[]
  brands: string[]
  models: string[]
  categories: string[]
}

type WorkbenchPageProps = {
  mode?: 'default' | 'data-adjustment'
}

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

type DataRow = {
  id: number
  sequence: number
  year: number | null
  month: number | null
  category_name: string | null
  platform: string | null
  item_name: string | null
  item_url: string | null
  item_image: string | null
  brand_raw: string | null
  brand_code: string | null
  brand_name: string | null
  model_code: string | null
  model_name: string | null
  model_aliases: string[]
  judgement_type: string | null
  sales_qty: number | null
  ref_price: number | null
  operator: string | null
  operated_at: string | null
  shop_name: string | null
  calc_price: number | null
  corrected_sales_qty: number | null
  corrected_sales_amount: number | null
  category_lv0: string | null
  category_lv1: string | null
  category_lv2: string | null
}

function AttrPopoverContent({ itemId }: { itemId: number }) {
  const [attrs, setAttrs] = useState<{ attr_name: string; attr_value: string }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchItemAttrs(itemId)
      .then(setAttrs)
      .finally(() => setLoading(false))
  }, [itemId])

  if (loading) return <Spin size="small" />
  if (attrs.length === 0) return <span style={{ color: '#999' }}>暂无属性</span>
  return (
    <List
      size="small"
      dataSource={attrs}
      renderItem={a => (
        <List.Item style={{ padding: '2px 0' }}>
          <strong>{a.attr_name}</strong>: {a.attr_value}
        </List.Item>
      )}
    />
  )
}

export default function WorkbenchPage({ mode = 'default' }: WorkbenchPageProps) {
  const [form] = Form.useForm()
  const [searchParams] = useSearchParams()
  const currentUser = readStoredUser()
  const { options: categoryOptions } = useCategoryOptions()
  const [filters, setFilters] = useState<FilterOptions>({
    years: [], months: [], platforms: [], brands: [], models: [], categories: [],
  })
  const [filtersLoaded, setFiltersLoaded] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [queryParams, setQueryParams] = useState<Record<string, unknown>>({})
  const [exporting, setExporting] = useState(false)
  const [exportProgress, setExportProgress] = useState(0)
  const [exportError, setExportError] = useState('')
  const [exportProgressVisible, setExportProgressVisible] = useState(false)
  const exportPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [total, setTotal] = useState(0)
  const [dataSource, setDataSource] = useState<DataRow[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(mode === 'data-adjustment')
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [exportStatuses, setExportStatuses] = useState<string[]>(['matched', 'confirmed', 'url_matched'])
  const [exportYear, setExportYear] = useState<number | undefined>(undefined)
  const [exportQuarter, setExportQuarter] = useState<number | undefined>(undefined)
  const cleanJobId = mode === 'data-adjustment' ? searchParams.get('clean_job_id') : null
  const modeParams = useMemo<Record<string, unknown>>(
    () => cleanJobId ? { clean_job_id: cleanJobId } : {},
    [cleanJobId],
  )
  const visibleCategoryOptions = useMemo(() => {
    const optionNames = new Set(filters.categories)
    const allOptions = categoryOptions
      .filter(c => optionNames.has(c.label))
      .map(c => ({ value: c.label, label: c.label, code: c.value }))
    if (!currentUser) return allOptions
    if (currentUser.is_admin === 1) return allOptions
    if (!currentUser.category_permissions?.length) return allOptions
    const allowed = new Set(currentUser.category_permissions)
    return allOptions.filter(c => allowed.has(c.code))
  }, [categoryOptions, currentUser, filters.categories])

  // 页面加载时拉取筛选枚举
  useEffect(() => {
    getWorkbenchFilters()
      .then(r => { setFilters(r.data); setFiltersLoaded(true) })
      .catch(() => setFiltersLoaded(true))
  }, [])

  // 查询
  useEffect(() => {
    if (!searched) return
    setLoading(true)
    queryWorkbenchData({ ...queryParams, ...modeParams, page, page_size: pageSize })
      .then(r => {
        setDataSource(r.data.items)
        setTotal(r.data.total)
      })
      .finally(() => setLoading(false))
  }, [queryParams, modeParams, page, pageSize, searched])

  const handleSearch = () => {
    const vals = form.getFieldsValue()
    setQueryParams(
      Object.fromEntries(Object.entries(vals).filter(([, v]) => v !== undefined && v !== '' && v !== null))
    )
    setPage(1)
    setSearched(true)
  }

  const handleReset = () => {
    form.resetFields()
    setQueryParams({})
    setPage(1)
    setSearched(false)
    setDataSource([])
    setTotal(0)
  }

  const stopExportPoll = () => {
    if (exportPollRef.current) {
      clearInterval(exportPollRef.current)
      exportPollRef.current = null
    }
  }

  useEffect(() => {
    return () => {
      if (exportPollRef.current) {
        clearInterval(exportPollRef.current)
        exportPollRef.current = null
      }
    }
  }, [])

  const handleExport = async () => {
    if (exportPollRef.current) return
    setExportModalOpen(false)
    setExporting(true)
    setExportProgress(0)
    setExportError('')
    setExportProgressVisible(true)
    try {
      const vals = form.getFieldsValue()
      const res = await exportWorkbench({
        ...modeParams,
        year: vals.year ?? exportYear,
        month: vals.month,
        category_name: vals.category_name,
        platform: vals.platform,
        brand_code: vals.brand_code,
        model_code: vals.model_code,
        item_url: vals.item_url,
        keyword: vals.keyword,
        statuses: exportStatuses,
        quarter: exportQuarter,
      })
      const { job_id } = res.data as { job_id: number }

      let pollFailCount = 0
      exportPollRef.current = setInterval(async () => {
        try {
          const jobRes = await getWorkbenchExportJob(job_id)
          const { status, progress, download_url, error_msg } = jobRes.data
          pollFailCount = 0  // reset on success
          setExportProgress(progress)
          if (status === 'done' && download_url) {
            stopExportPoll()
            setExportProgress(100)
            setTimeout(() => {
              setExportProgressVisible(false)
              setExporting(false)
              const a = document.createElement('a')
              a.href = download_url
              a.click()
            }, 800)
          } else if (status === 'error') {
            stopExportPoll()
            setExportError(error_msg || '导出失败，请重试')
            setExporting(false)
          }
        } catch {
          pollFailCount++
          if (pollFailCount >= 10) {
            stopExportPoll()
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

  const columns = [
    { title: '序号', dataIndex: 'sequence', width: 70, fixed: 'left' as const },
    { title: '年度', dataIndex: 'year', width: 70 },
    { title: '月度', dataIndex: 'month', width: 90 },
    { title: '品类', dataIndex: 'category_name', width: 120, ellipsis: true },
    { title: '平台', dataIndex: 'platform', width: 80 },
    {
      title: '商品名称', dataIndex: 'item_name', width: 260, ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip>
      ),
    },
    {
      title: '网址', width: 70,
      render: (_: unknown, row: DataRow) =>
        row.item_url
          ? <a href={row.item_url} target="_blank" rel="noreferrer"><LinkOutlined /> 查看</a>
          : '-',
    },
    {
      title: '图片地址', width: 90,
      render: (_: unknown, row: DataRow) =>
        row.item_image
          ? <a href={row.item_image} target="_blank" rel="noreferrer">查看图片</a>
          : '-',
    },
    { title: '原品牌', dataIndex: 'brand_raw', width: 110, ellipsis: true },
    {
      title: '型号', dataIndex: 'model_code', width: 110,
      render: (_: unknown, record: DataRow) => (
        <span>
          {record.model_code ?? '-'}
          {record.model_code && (
            <Popover
              title="属性"
              trigger="click"
              content={<AttrPopoverContent itemId={record.id} />}
            >
              <InfoCircleOutlined style={{ marginLeft: 4, cursor: 'pointer', color: '#8c8c8c' }} />
            </Popover>
          )}
        </span>
      ),
    },
    {
      title: '型号别名', dataIndex: 'model_aliases', width: 150, ellipsis: true,
      render: (v: string[]) => v?.length ? v.join('、') : '-',
    },
    { title: '判断类型', dataIndex: 'judgement_type', width: 120, ellipsis: true },
    {
      title: '销量', dataIndex: 'sales_qty', width: 80,
      render: (v: number | null) => v ?? '-',
    },
    {
      title: '平均价格', dataIndex: 'ref_price', width: 100,
      render: (v: number | null) => v != null ? `¥${v.toFixed(2)}` : '-',
    },
    { title: '操作人', dataIndex: 'operator', width: 90, render: (v: string | null) => v || '-' },
    { title: '操作时间', dataIndex: 'operated_at', width: 160, render: (v: string | null) => v || '-' },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 筛选面板 */}
      <Card>
        <Form form={form} layout="inline" style={{ rowGap: 8 }}>
          <Form.Item name="year" style={{ marginBottom: 8 }}>
            <Select
              placeholder="年度"
              allowClear
              style={{ width: 100 }}
              options={filters.years.map(y => ({ value: y, label: String(y) }))}
            />
          </Form.Item>
          <Form.Item name="month" style={{ marginBottom: 8 }}>
            <Select
              placeholder="月度"
              allowClear
              style={{ width: 110 }}
              options={filters.months.map(m => ({ value: m, label: String(m) }))}
            />
          </Form.Item>
          <Form.Item name="category_name" style={{ marginBottom: 8 }}>
            <Select
              showSearch
              placeholder="品类"
              allowClear
              style={{ width: 150 }}
              options={visibleCategoryOptions}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="platform" style={{ marginBottom: 8 }}>
            <Select
              placeholder="平台"
              allowClear
              style={{ width: 110 }}
              options={filters.platforms.map(p => ({ value: p, label: p }))}
            />
          </Form.Item>
          <Form.Item name="brand_code" style={{ marginBottom: 8 }}>
            <Select
              showSearch
              placeholder="品牌"
              allowClear
              style={{ width: 140 }}
              options={filters.brands.map(b => ({ value: b, label: b }))}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="model_code" style={{ marginBottom: 8 }}>
            <Select
              showSearch
              placeholder="型号"
              allowClear
              style={{ width: 140 }}
              options={filters.models.map(m => ({ value: m, label: m }))}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="item_url" style={{ marginBottom: 8 }}>
            <Input
              placeholder="网址"
              allowClear
              style={{ width: 180 }}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item name="keyword" style={{ marginBottom: 8 }}>
            <Input
              placeholder="搜索宝贝名称"
              allowClear
              style={{ width: 200 }}
              prefix={<SearchOutlined />}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Space>
              <Button
                type="primary"
                icon={<SearchOutlined />}
                onClick={handleSearch}
                loading={!filtersLoaded}
              >
                查询
              </Button>
              <Button icon={<ClearOutlined />} onClick={handleReset}>重置</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* 结果表格 */}
      {searched && (
        <Card
          extra={
            <Row align="middle" gutter={16}>
              <Col>
                <Statistic
                  value={total}
                  suffix="条"
                  valueStyle={{ fontSize: 14, color: '#1677ff' }}
                />
              </Col>
              <Col>
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={exporting}
                  disabled={total === 0}
                  onClick={() => setExportModalOpen(true)}
                >
                  导出全部（{total} 条）
                </Button>
              </Col>
            </Row>
          }
        >
          <Table
            dataSource={dataSource}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            scroll={{ x: 1780 }}
            pagination={{
              current: page,
              pageSize,
              total,
              onChange: (p, ps) => { setPage(p); setPageSize(ps) },
              showTotal: t => `共 ${t} 条`,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100'],
            }}
          />
        </Card>
      )}

      <Modal
        title="导出配置"
        open={exportModalOpen}
        onCancel={() => setExportModalOpen(false)}
        onOk={handleExport}
        okButtonProps={{ disabled: exportStatuses.length === 0 }}
        okText="确认导出"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>导出范围（状态）</div>
            <Checkbox.Group
              value={exportStatuses}
              onChange={vals => setExportStatuses(vals as string[])}
              options={[
                { label: '已匹配', value: 'matched' },
                { label: '已确认', value: 'confirmed' },
                { label: 'URL匹配', value: 'url_matched' },
                { label: '待确认', value: 'pending' },
              ]}
            />
          </div>
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>时间筛选（可选）</div>
            <Space>
              <Select
                allowClear
                placeholder="年份"
                style={{ width: 100 }}
                value={exportYear}
                onChange={setExportYear}
                options={[2024, 2025, 2026].map(y => ({ label: String(y), value: y }))}
              />
              <Select
                allowClear
                placeholder="季度"
                style={{ width: 100 }}
                value={exportQuarter}
                onChange={setExportQuarter}
                options={[
                  { label: 'Q1', value: 1 },
                  { label: 'Q2', value: 2 },
                  { label: 'Q3', value: 3 },
                  { label: 'Q4', value: 4 },
                ]}
              />
            </Space>
          </div>
        </Space>
      </Modal>

      <ProgressModal
        visible={exportProgressVisible}
        title="正在导出数据..."
        progress={exportProgress}
        errorMsg={exportError}
      />
    </Space>
  )
}
