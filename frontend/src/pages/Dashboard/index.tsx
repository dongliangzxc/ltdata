import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Checkbox, Col, Form, Input, Modal, Row, Select, Segmented, Space, Statistic, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  AnalyticsGroupBy,
  AnalyticsSummaryParams,
  AnalyticsSummaryResponse,
  AnalyticsSummaryRow,
  exportAnalyticsDetail,
  exportAnalyticsSummary,
  getAnalyticsFilters,
  getAnalyticsSummary,
  type UserProfile,
} from '../../services/api'

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

const SORT_BY = 'corrected_sales_qty_desc'

const detailFieldOptions = [
  { label: '平台', value: 'platform' },
  { label: '月份', value: 'month' },
  { label: '品类', value: 'category_name' },
  { label: '商品ID', value: 'item_id' },
  { label: '商品名', value: 'item_name' },
  { label: '店铺', value: 'shop_name' },
  { label: '品牌编码', value: 'brand_code' },
  { label: '品牌名称', value: 'brand_name' },
  { label: '型号编码', value: 'model_code' },
  { label: '型号名称', value: 'model_name' },
  { label: '原始销量', value: 'sales_qty' },
  { label: '修正后销量', value: 'corrected_sales_qty' },
  { label: '原始销额', value: 'sales_amount' },
  { label: '原始价格', value: 'price' },
  { label: '发布时间', value: 'published_at' },
]

const groupOptions = [
  { label: '型号', value: 'model' },
  { label: '品牌', value: 'brand' },
  { label: '品类', value: 'category' },
  { label: '平台', value: 'platform' },
]

type FilterValues = {
  year?: number
  month?: number
  platform?: string
  brand?: string
  category?: string
  model_keyword?: string
  item_keyword?: string
}

function cleanParams(values: FilterValues): FilterValues {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== '')
  ) as FilterValues
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString()
}

function formatDecimal(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function openDownload(downloadUrl?: string) {
  if (!downloadUrl) {
    message.error('导出失败，未返回下载链接')
    return
  }

  let url: URL
  try {
    url = new URL(downloadUrl, window.location.origin)
  } catch {
    message.error('导出失败，下载链接格式错误')
    return
  }

  if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/analytics/download/')) {
    message.error('导出失败，下载链接不合法')
    return
  }

  window.location.href = url.toString()
}

export default function DashboardPage() {
  const [form] = Form.useForm<FilterValues>()
  const [filterOptions, setFilterOptions] = useState<{
    years: number[]
    months: number[]
    platforms: string[]
    brands: { brand_code: string; brand_name: string | null }[]
    categories: { category_name: string }[]
  }>({ years: [], months: [], platforms: [], brands: [], categories: [] })
  const currentUser = readStoredUser()
  const visibleCategories = useMemo(() => {
    if (!currentUser) return filterOptions.categories
    if (currentUser.is_admin === 1) return filterOptions.categories
    if (!currentUser.category_permissions?.length) return filterOptions.categories
    return filterOptions.categories
  }, [filterOptions.categories, currentUser])
  const categoryOptions = useMemo(
    () => visibleCategories.map(category => ({ label: category.category_name, value: category.category_name })),
    [visibleCategories],
  )
  const [queryParams, setQueryParams] = useState<FilterValues>({})
  const [groupBy, setGroupBy] = useState<AnalyticsGroupBy>('model')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [selectedFields, setSelectedFields] = useState<string[]>(detailFieldOptions.map(item => item.value))
  const [summary, setSummary] = useState<AnalyticsSummaryResponse>({
    totals: { sales_qty: 0, corrected_sales_qty: 0, sales_amount: 0, avg_price: null, record_count: 0 },
    rows: [],
    total: 0,
    page: 1,
    page_size: 20,
  })
  const summaryRequestIdRef = useRef(0)

  const requestParams = useMemo<AnalyticsSummaryParams>(() => ({
    ...queryParams,
    group_by: groupBy,
    page,
    page_size: pageSize,
    sort_by: SORT_BY,
  }), [queryParams, groupBy, page, pageSize])

  const exportParams = useMemo<AnalyticsSummaryParams>(() => ({
    ...queryParams,
    group_by: groupBy,
    sort_by: SORT_BY,
  }), [queryParams, groupBy])

  const columns: ColumnsType<AnalyticsSummaryRow> = [
    {
      title: '维度名称',
      dataIndex: 'dimension_name',
      ellipsis: true,
      render: (value: string | null, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value || '-'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{row.dimension_key || '-'}</Text>
        </Space>
      ),
    },
    {
      title: '聚合维度',
      dataIndex: 'group_by',
      width: 100,
      render: (value: AnalyticsGroupBy) => groupOptions.find(item => item.value === value)?.label || value,
    },
    {
      title: '原始销量',
      dataIndex: 'sales_qty',
      width: 130,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '修正后销量',
      dataIndex: 'corrected_sales_qty',
      width: 140,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '原始销额',
      dataIndex: 'sales_amount',
      width: 140,
      align: 'right',
      render: formatDecimal,
    },
    {
      title: '原始均价',
      dataIndex: 'avg_price',
      width: 120,
      align: 'right',
      render: (value: number | null) => value == null ? '-' : value.toFixed(2),
    },
    {
      title: '记录数',
      dataIndex: 'record_count',
      width: 100,
      align: 'right',
      render: formatNumber,
    },
  ]

  useEffect(() => {
    let cancelled = false

    getAnalyticsFilters().then(response => {
      if (!cancelled) setFilterOptions(response.data)
    })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const requestId = summaryRequestIdRef.current + 1
    summaryRequestIdRef.current = requestId
    setLoading(true)

    getAnalyticsSummary(requestParams)
      .then(response => {
        if (cancelled || summaryRequestIdRef.current !== requestId) return

        setSummary(response.data)
        if (response.data.page !== page) setPage(response.data.page)
        if (response.data.page_size !== pageSize) setPageSize(response.data.page_size)
      })
      .finally(() => {
        if (!cancelled && summaryRequestIdRef.current === requestId) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [requestParams])

  const handleSearch = () => {
    setPage(1)
    setQueryParams(cleanParams(form.getFieldsValue()))
  }

  const handleReset = () => {
    form.resetFields()
    setGroupBy('model')
    setPage(1)
    setQueryParams({})
  }

  const handleGroupChange = (value: string | number) => {
    setGroupBy(value as AnalyticsGroupBy)
    setPage(1)
  }

  const handleExportSummary = async () => {
    setExporting(true)
    try {
      const response = await exportAnalyticsSummary(exportParams)
      if (response.data.status === 'done' && response.data.download_url) {
        message.success('已生成汇总导出')
        openDownload(response.data.download_url)
        return
      }

      message.warning('导出任务已提交，请稍后下载')
    } finally {
      setExporting(false)
    }
  }

  const handleOpenDetailExport = () => {
    setSelectedFields(detailFieldOptions.map(item => item.value))
    setDetailModalOpen(true)
  }

  const handleExportDetail = async () => {
    if (selectedFields.length === 0) {
      message.warning('请至少选择一个导出字段')
      return
    }

    setExporting(true)
    try {
      const response = await exportAnalyticsDetail({ ...queryParams, fields: selectedFields.join(',') })
      if (response.data.status === 'done' && response.data.download_url) {
        message.success('已生成明细导出')
        setDetailModalOpen(false)
        openDownload(response.data.download_url)
        return
      }

      message.warning('导出任务已提交，请稍后下载')
    } finally {
      setExporting(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card>
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item name="year" label="年份">
                <Select allowClear placeholder="全部年份" options={filterOptions.years.map(year => ({ label: year, value: year }))} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item name="month" label="月份">
                <Select allowClear placeholder="全部月份" options={filterOptions.months.map(month => ({ label: `${month}月`, value: month }))} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item name="platform" label="平台">
                <Select allowClear placeholder="全部平台" options={filterOptions.platforms.map(platform => ({ label: platform, value: platform }))} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item name="brand" label="品牌">
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="全部品牌"
                  options={filterOptions.brands.map(brand => ({
                    label: brand.brand_name ? `${brand.brand_code} / ${brand.brand_name}` : brand.brand_code,
                    value: brand.brand_code,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item name="category" label="品类">
                <Select allowClear showSearch optionFilterProp="label" placeholder="全部品类" options={categoryOptions} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8} lg={4}>
              <Form.Item label="操作">
                <Space>
                  <Button type="primary" onClick={handleSearch}>查询</Button>
                  <Button onClick={handleReset}>重置</Button>
                </Space>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="model_keyword" label="型号关键词">
                <Input allowClear placeholder="型号编码或型号名称" onPressEnter={handleSearch} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="item_keyword" label="商品关键词">
                <Input allowClear placeholder="商品名称关键词" onPressEnter={handleSearch} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="原始销量" value={summary.totals.sales_qty} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="修正后销量" value={summary.totals.corrected_sales_qty} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="原始销额" value={summary.totals.sales_amount} precision={2} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card>
            {summary.totals.avg_price == null ? (
              <Statistic title="原始均价" value="-" />
            ) : (
              <Statistic title="原始均价" value={summary.totals.avg_price} precision={2} />
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card><Statistic title="记录数" value={summary.totals.record_count} /></Card>
        </Col>
      </Row>

      <Card
        title="聚合分析"
        extra={(
          <Space wrap>
            <Segmented value={groupBy} options={groupOptions} onChange={handleGroupChange} />
            <Button loading={exporting} onClick={handleExportSummary}>导出汇总</Button>
            <Button loading={exporting} onClick={handleOpenDetailExport}>导出明细</Button>
          </Space>
        )}
      >
        <Table
          rowKey={row => `${row.group_by}-${row.dimension_key}`}
          loading={loading}
          columns={columns}
          dataSource={summary.rows}
          pagination={{
            current: summary.page,
            pageSize: summary.page_size,
            total: summary.total,
            showSizeChanger: true,
            showTotal: total => `共 ${total} 条`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage)
              setPageSize(nextPageSize)
            },
          }}
        />
      </Card>

      <Modal
        title="导出明细字段"
        open={detailModalOpen}
        onCancel={() => setDetailModalOpen(false)}
        onOk={handleExportDetail}
        okButtonProps={{ disabled: selectedFields.length === 0 }}
        confirmLoading={exporting}
        width={720}
      >
        <Checkbox.Group
          value={selectedFields}
          options={detailFieldOptions}
          onChange={values => setSelectedFields(values as string[])}
          style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', rowGap: 12 }}
        />
      </Modal>
    </Space>
  )
}
