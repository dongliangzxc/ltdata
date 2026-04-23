import { useState } from 'react'
import {
  Card, Table, Select, Input, Row, Col, Statistic, Space, Tag
} from 'antd'
import type { TableProps } from 'antd'
import {
  ShoppingCartOutlined, DollarOutlined, TagsOutlined, AppstoreOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listRawData, getRawStats, getRawFilters, listUploadFiles } from '../../services/api'

const PLATFORM_LABEL: Record<string, string> = { JD: '京东', TM: '天猫', TB: '淘宝' }

const renderVal = (v: unknown) => (v == null || v === '' ? '-' : String(v))

const tableColumns = [
  {
    title: '平台', dataIndex: 'platform', width: 90, fixed: 'left' as const,
    render: (v: string) => {
      if (!v) return '-'
      const label = Object.entries(PLATFORM_LABEL).find(([, name]) => v.includes(name))?.[1] ?? v
      return <Tag color="blue">{label}</Tag>
    }
  },
  { title: '月份', dataIndex: 'month', width: 90, sorter: true, render: renderVal },
  { title: '品牌', dataIndex: 'brand_std', width: 110, fixed: 'left' as const, render: renderVal },
  { title: '机型', dataIndex: 'model_std', width: 130, render: renderVal },
  { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true, width: 280, render: renderVal },
  { title: '店铺', dataIndex: 'shop_name', ellipsis: true, width: 200, render: renderVal },
  { title: '销量', dataIndex: 'sales_qty', width: 80, sorter: true, render: renderVal },
  {
    title: '销售额', dataIndex: 'sales_amount', width: 110, sorter: true,
    render: (v: number) => v != null ? `¥${Number(v).toLocaleString()}` : '-'
  },
  {
    title: '价格', dataIndex: 'price', width: 90, sorter: true,
    render: (v: number) => v != null ? `¥${Number(v).toFixed(2)}` : '-'
  },
  {
    title: '商品链接', dataIndex: 'item_url', width: 100,
    render: (v: string) => v ? <a href={v} target="_blank" rel="noreferrer">查看</a> : '-'
  },
]

export default function DataListPage() {
  const [filters, setFilters] = useState<Record<string, unknown>>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [sortBy, setSortBy] = useState<string | undefined>()
  const [sortOrder, setSortOrder] = useState<string>('desc')

  const { data: filterOptions } = useRequest(() => getRawFilters().then(r => r.data))
  const { data: filesData } = useRequest(() => listUploadFiles().then(r => r.data))

  const queryParams = { ...filters, page, page_size: pageSize, sort_by: sortBy, sort_order: sortOrder }

  const { data: tableData, loading } = useRequest(
    () => listRawData(queryParams).then(r => r.data),
    { refreshDeps: [JSON.stringify(queryParams)] }
  )

  const { data: stats } = useRequest(
    () => getRawStats(filters).then(r => r.data),
    { refreshDeps: [JSON.stringify(filters)] }
  )

  const updateFilter = (key: string, val: unknown) => {
    setFilters(prev => ({ ...prev, [key]: val || undefined }))
    setPage(1)
  }

  const handleTableChange: TableProps['onChange'] = (_pagination, _filters, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter
    if (s?.field && s?.order) {
      setSortBy(String(s.field))
      setSortOrder(s.order === 'ascend' ? 'asc' : 'desc')
    } else {
      setSortBy(undefined)
    }
    setPage(1)
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col span={6}>
          <Card><Statistic title="总销量" value={stats?.total_qty ?? 0} prefix={<ShoppingCartOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="总销售额（¥）" value={stats?.total_amount ?? 0} prefix={<DollarOutlined />} precision={0} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="品牌数" value={stats?.brand_count ?? 0} prefix={<TagsOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="型号数" value={stats?.model_count ?? 0} prefix={<AppstoreOutlined />} /></Card>
        </Col>
      </Row>

      <Card>
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={5}>
            <Select placeholder="选择文件" allowClear style={{ width: '100%' }} onChange={v => updateFilter('file_id', v)}>
              {(filesData ?? []).map((f: { id: number; filename: string }) => (
                <Select.Option key={f.id} value={f.id}>{f.filename}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={4}>
            <Select placeholder="平台" allowClear style={{ width: '100%' }} onChange={v => updateFilter('platform', v)}>
              {(filterOptions?.platforms ?? []).map((p: string) => (
                <Select.Option key={p} value={p}>{p}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={4}>
            <Select placeholder="月份" allowClear style={{ width: '100%' }} onChange={v => updateFilter('month', v)}>
              {(filterOptions?.months ?? []).map((m: number) => (
                <Select.Option key={m} value={m}>{m}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={5}>
            <Input placeholder="搜索品牌" allowClear onChange={e => updateFilter('brand_std', e.target.value)} />
          </Col>
        </Row>

        <Table
          dataSource={tableData?.items ?? []}
          columns={tableColumns}
          rowKey="id"
          size="small"
          loading={loading}
          scroll={{ x: 1300 }}
          onChange={handleTableChange}
          pagination={{
            current: page,
            pageSize,
            total: tableData?.total ?? 0,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </Card>
    </Space>
  )
}
