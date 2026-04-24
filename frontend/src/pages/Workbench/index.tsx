import { useState, useEffect } from 'react'
import {
  Card, Row, Col, Select, Input, Button, Table, Space,
  Typography, Tag, Tooltip, Form, Statistic, message
} from 'antd'
import { SearchOutlined, DownloadOutlined, ClearOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listCleanJobs, getWorkbenchFilters, queryWorkbenchData,
  exportWorkbenchData, getWorkbenchDownloadUrl
} from '../../services/api'

const { Text } = Typography

type FilterOptions = {
  months: number[]
  platforms: string[]
  brands: string[]
  categories: string[]
}

type DataRow = {
  id: number
  month: number | null
  platform: string | null
  item_name: string | null
  brand_raw: string | null
  shop_name: string | null
  ref_price: number | null
  sales_qty: number | null
  category_lv1: string | null
  category_lv2: string | null
  item_url: string | null
}

export default function WorkbenchPage() {
  const [form] = Form.useForm()
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [filters, setFilters] = useState<FilterOptions>({ months: [], platforms: [], brands: [], categories: [] })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [queryParams, setQueryParams] = useState<Record<string, unknown>>({})
  const [exporting, setExporting] = useState(false)
  const [total, setTotal] = useState(0)
  const [dataSource, setDataSource] = useState<DataRow[]>([])
  const [loading, setLoading] = useState(false)

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const doneJobs = (jobsData ?? []).filter((j: { status: string }) => j.status === 'done')

  // 任务变更后拉取筛选项枚举
  useEffect(() => {
    if (!selectedJobId) return
    getWorkbenchFilters(selectedJobId).then(r => setFilters(r.data))
    form.resetFields(['month', 'platform', 'brand_raw', 'category_lv1', 'keyword'])
    setQueryParams({ clean_job_id: selectedJobId })
    setPage(1)
  }, [selectedJobId])

  // 查询数据
  useEffect(() => {
    if (!queryParams.clean_job_id) return
    setLoading(true)
    queryWorkbenchData({ ...queryParams, page, page_size: pageSize })
      .then(r => {
        setDataSource(r.data.items)
        setTotal(r.data.total)
      })
      .finally(() => setLoading(false))
  }, [queryParams, page, pageSize])

  const handleSearch = () => {
    const vals = form.getFieldsValue()
    setQueryParams({
      clean_job_id: selectedJobId,
      ...Object.fromEntries(Object.entries(vals).filter(([, v]) => v !== undefined && v !== '' && v !== null)),
    })
    setPage(1)
  }

  const handleReset = () => {
    form.resetFields()
    setQueryParams({ clean_job_id: selectedJobId })
    setPage(1)
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
            : <Text style={{ fontSize: 12 }}>{v}</Text>
          }
        </Tooltip>
      )
    },
    { title: '品牌', dataIndex: 'brand_raw', width: 110 },
    { title: '店铺', dataIndex: 'shop_name', width: 130, ellipsis: true },
    {
      title: '参考价', dataIndex: 'ref_price', width: 80,
      render: (v: number | null) => v != null ? `¥${v.toFixed(2)}` : '-'
    },
    {
      title: '销量', dataIndex: 'sales_qty', width: 70,
      render: (v: number | null) => v ?? '-'
    },
    {
      title: '类目', width: 160, ellipsis: true,
      render: (_: unknown, row: DataRow) => (
        <Space size={2} wrap>
          {row.category_lv1 && <Tag style={{ fontSize: 11 }}>{row.category_lv1}</Tag>}
          {row.category_lv2 && <Tag style={{ fontSize: 11 }}>{row.category_lv2}</Tag>}
        </Space>
      )
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 任务选择 */}
      <Card>
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>选择清洗任务：</Text>
          </Col>
          <Col flex="220px">
            <Select
              style={{ width: '100%' }}
              placeholder="选择任务"
              value={selectedJobId}
              onChange={v => setSelectedJobId(v)}
              options={doneJobs.map((j: { id: number; created_at: string; row_out: number }) => ({
                value: j.id,
                label: `任务#${j.id}（${j.row_out}条，${new Date(j.created_at).toLocaleDateString('zh-CN')}）`,
              }))}
            />
          </Col>
        </Row>
      </Card>

      {/* 筛选面板 */}
      {selectedJobId && (
        <Card>
          <Form form={form} layout="inline" style={{ gap: 8 }}>
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
            <Form.Item name="brand_raw" style={{ marginBottom: 8 }}>
              <Select
                showSearch
                placeholder="品牌"
                allowClear
                style={{ width: 160 }}
                options={filters.brands.map(b => ({ value: b, label: b }))}
                filterOption={(input, option) =>
                  (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
                }
              />
            </Form.Item>
            <Form.Item name="category_lv1" style={{ marginBottom: 8 }}>
              <Select
                showSearch
                placeholder="一级类目"
                allowClear
                style={{ width: 160 }}
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
                <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
                <Button icon={<ClearOutlined />} onClick={handleReset}>重置</Button>
              </Space>
            </Form.Item>
          </Form>
        </Card>
      )}

      {/* 结果表格 */}
      {selectedJobId && (
        <Card
          extra={
            <Space>
              <Statistic
                value={total}
                suffix="条"
                valueStyle={{ fontSize: 14, color: '#1677ff' }}
              />
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={exporting}
                disabled={total === 0}
                onClick={handleExport}
              >
                导出全部（{total} 条）
              </Button>
            </Space>
          }
        >
          <Table
            dataSource={dataSource}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            scroll={{ x: 1000 }}
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
