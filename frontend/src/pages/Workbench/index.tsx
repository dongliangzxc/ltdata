import { useState, useEffect } from 'react'
import {
  Card, Row, Col, Select, Input, Button, Table,
  Typography, Tooltip, Form, Statistic, message, Space
} from 'antd'
import { SearchOutlined, DownloadOutlined, ClearOutlined } from '@ant-design/icons'
import {
  getWorkbenchFilters, queryWorkbenchData,
  exportWorkbenchData, getWorkbenchDownloadUrl
} from '../../services/api'

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
  category_name: string | null
  category_lv1: string | null
  category_lv2: string | null
  item_url: string | null
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
  const [total, setTotal] = useState(0)
  const [dataSource, setDataSource] = useState<DataRow[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

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

  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await exportWorkbenchData(queryParams)
      const { token, filename, rows } = res.data
      message.success(`正在下载：${filename}（共 ${rows} 条）`)
      const a = document.createElement('a')
      a.href = getWorkbenchDownloadUrl(token)
      a.download = filename
      a.click()
    } finally {
      setExporting(false)
    }
  }

  const columns = [
    { title: '月份', dataIndex: 'month', width: 70 },
    { title: '平台', dataIndex: 'platform', width: 70 },
    {
      title: '宝贝名称', dataIndex: 'item_name', ellipsis: true,
      render: (v: string, row: DataRow) => (
        <Tooltip title={v}>
          {row.item_url
            ? <a href={row.item_url} target="_blank" rel="noreferrer"><Text style={{ fontSize: 12 }}>{v}</Text></a>
            : <Text style={{ fontSize: 12 }}>{v}</Text>}
        </Tooltip>
      ),
    },
    { title: '品牌', dataIndex: 'brand_code', width: 90 },
    { title: '型号', dataIndex: 'model_code', width: 100 },
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
      title: '品类', dataIndex: 'category_name', width: 110, ellipsis: true,
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
                  onClick={handleExport}
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
    </Space>
  )
}
