import { useState, useEffect, useRef } from 'react'
import {
  Card, Row, Col, Select, Input, Button, Table,
  Typography, Tooltip, Form, Statistic, Space,
  Popover, Spin, List, Checkbox, Modal
} from 'antd'
import { SearchOutlined, DownloadOutlined, ClearOutlined, LinkOutlined, InfoCircleOutlined } from '@ant-design/icons'
import {
  getWorkbenchFilters, queryWorkbenchData,
  getWorkbenchExportJob,
  exportWorkbench, fetchItemAttrs
} from '../../services/api'
import ProgressModal from '../../components/ProgressModal'

const { Text } = Typography

type FilterOptions = {
  months: number[]
  platforms: string[]
  brands: string[]
  models: string[]
  categories: string[]
}

type DataRow = {
  id: number
  month: number | null
  platform: string | null
  item_name: string | null
  brand_code: string | null
  brand_name: string | null
  model_code: string | null
  model_name: string | null
  shop_name: string | null
  ref_price: number | null
  sales_qty: number | null
  calc_price: number | null
  corrected_sales_qty: number | null
  corrected_sales_amount: number | null
  category_name: string | null
  category_lv0: string | null
  category_lv1: string | null
  category_lv2: string | null
  item_url: string | null
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

export default function WorkbenchPage() {
  const [form] = Form.useForm()
  const [filters, setFilters] = useState<FilterOptions>({
    months: [], platforms: [], brands: [], models: [], categories: [],
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
  const [searched, setSearched] = useState(false)
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [exportStatuses, setExportStatuses] = useState<string[]>(['matched', 'confirmed', 'url_matched'])
  const [exportYear, setExportYear] = useState<number | undefined>(undefined)
  const [exportQuarter, setExportQuarter] = useState<number | undefined>(undefined)

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
    queryWorkbenchData({ ...queryParams, page, page_size: pageSize })
      .then(r => {
        setDataSource(r.data.items)
        setTotal(r.data.total)
      })
      .finally(() => setLoading(false))
  }, [queryParams, page, pageSize, searched])

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

  const handleExport = async () => {
    setExportModalOpen(false)
    setExporting(true)
    setExportProgress(0)
    setExportError('')
    setExportProgressVisible(true)
    try {
      const vals = form.getFieldsValue()
      const res = await exportWorkbench({
        month: vals.month,
        platform: vals.platform,
        brand_code: vals.brand_code,
        model_code: vals.model_code,
        category_name: vals.category_name,
        keyword: vals.keyword,
        statuses: exportStatuses,
        year: exportYear,
        quarter: exportQuarter,
      })
      const { job_id } = res.data as { job_id: number }

      exportPollRef.current = setInterval(async () => {
        try {
          const jobRes = await getWorkbenchExportJob(job_id)
          const { status, progress, download_url, error_msg } = jobRes.data
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
          // 忽略轮询网络错误
        }
      }, 1000)
    } catch {
      setExportProgressVisible(false)
      setExporting(false)
    }
  }

  const columns = [
    { title: '月份', dataIndex: 'month', width: 70 },
    { title: '平台', dataIndex: 'platform', width: 70 },
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip>
      ),
    },
    {
      title: '链接', width: 60,
      render: (_: unknown, row: DataRow) =>
        row.item_url
          ? <a href={row.item_url} target="_blank" rel="noreferrer"><LinkOutlined /></a>
          : '-',
    },
    { title: '品牌', dataIndex: 'brand_code', width: 90 },
    {
      title: '型号', dataIndex: 'model_code', width: 100,
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
    { title: '型号名称', dataIndex: 'model_name', width: 120, ellipsis: true },
    { title: '店铺', dataIndex: 'shop_name', width: 130, ellipsis: true },
    {
      title: '参考价', dataIndex: 'ref_price', width: 85,
      render: (v: number | null) => v != null ? `¥${v.toFixed(2)}` : '-',
    },
    {
      title: '销量', dataIndex: 'sales_qty', width: 70,
      render: (v: number | null) => v ?? '-',
    },
    {
      title: '计算价格', dataIndex: 'calc_price', width: 85,
      render: (v: number | null) => v != null ? `¥${v.toFixed(2)}` : '-',
    },
    {
      title: '修正销量', dataIndex: 'corrected_sales_qty', width: 80,
      render: (v: number | null) => v ?? '-',
    },
    {
      title: '修正销售额', dataIndex: 'corrected_sales_amount', width: 100,
      render: (v: number | null) => v != null ? `¥${v.toFixed(2)}` : '-',
    },
    {
      title: '品类', dataIndex: 'category_name', width: 110, ellipsis: true,
    },
    {
      title: 'LV0类目', dataIndex: 'category_lv0', width: 90,
      render: (v: string | null) => v ?? '-',
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 筛选面板 */}
      <Card>
        <Form form={form} layout="inline" style={{ rowGap: 8 }}>
          <Form.Item name="month" style={{ marginBottom: 8 }}>
            <Select
              placeholder="月份"
              allowClear
              style={{ width: 110 }}
              options={filters.months.map(m => ({ value: m, label: String(m) }))}
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
          <Form.Item name="category_name" style={{ marginBottom: 8 }}>
            <Select
              showSearch
              placeholder="品类"
              allowClear
              style={{ width: 150 }}
              options={filters.categories.map(c => ({ value: c, label: c }))}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
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
            scroll={{ x: 1100 }}
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
