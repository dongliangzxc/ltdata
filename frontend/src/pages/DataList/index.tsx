import { useState, useRef, useCallback } from 'react'
import {
  Card, Table, Select, Input, Row, Col, Statistic, Space, Tag, Button, message, InputNumber
} from 'antd'
import type { TableProps, TableColumnType } from 'antd'
import {
  ShoppingCartOutlined, DollarOutlined, TagsOutlined, AppstoreOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { listRawData, getRawStats, getRawFilters, listUploadFiles, exportRawData } from '../../services/api'

const PLATFORM_LABEL: Record<string, string> = { JD: '京东', TM: '天猫', TB: '淘宝' }

const renderVal = (v: unknown) => (v == null || v === '' ? '-' : String(v))

// 渲染品牌：brand_std 优先，为空则 fallback 到 brand_raw
const renderBrand = (v: unknown, row: Record<string, unknown>) => {
  const val = v || row.brand_raw
  return val == null || val === '' ? '-' : String(val)
}

// 可拖拽列宽的表头渲染器
function ResizableTitle(props: React.ThHTMLAttributes<HTMLTableCellElement> & { width?: number; onResize?: (w: number) => void }) {
  const { onResize, width, ...restProps } = props
  const startX = useRef(0)
  const startW = useRef(0)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    startX.current = e.clientX
    startW.current = width ?? 100

    const onMouseMove = (me: MouseEvent) => {
      const newW = Math.max(50, startW.current + me.clientX - startX.current)
      onResize?.(newW)
    }
    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [width, onResize])

  if (!onResize) return <th {...restProps} />

  return (
    <th {...restProps} style={{ ...restProps.style, position: 'relative' }}>
      {restProps.children}
      <span
        onMouseDown={handleMouseDown}
        style={{
          position: 'absolute', right: 0, top: 0, bottom: 0, width: 6,
          cursor: 'col-resize', zIndex: 1,
          background: 'transparent',
        }}
      />
    </th>
  )
}

type ColDef = TableColumnType<Record<string, unknown>> & { dataIndex?: string }

const BASE_COLUMNS: ColDef[] = [
  {
    title: '平台', dataIndex: 'platform', width: 90, fixed: 'left' as const,
    render: (v: string) => {
      if (!v) return '-'
      const label = Object.entries(PLATFORM_LABEL).find(([, name]) => v.includes(name))?.[1] ?? v
      return <Tag color="blue">{label}</Tag>
    }
  },
  { title: '月份', dataIndex: 'month', width: 90, sorter: true, render: renderVal },
  { title: '品牌', dataIndex: 'brand_std', width: 110, fixed: 'left' as const, render: renderBrand },
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
  const [colWidths, setColWidths] = useState<Record<string, number>>({})
  const [exporting, setExporting] = useState(false)

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

  const updatePriceFilter = (key: 'price_min' | 'price_max', value: number | null) => {
    setFilters(prev => ({ ...prev, [key]: value ?? undefined }))
    setPage(1)
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await exportRawData(filters)
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const a = document.createElement('a')
      document.body.appendChild(a)
      a.href = url
      a.download = 'rawdata_export.xlsx'
      a.click()
      document.body.removeChild(a)
      setTimeout(() => window.URL.revokeObjectURL(url), 100)
    } catch {
      message.error('导出失败，请重试')
    } finally {
      setExporting(false)
    }
  }

  const handleTableChange: TableProps<Record<string, unknown>>['onChange'] = (_pagination, _filters, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter
    if (s?.field && s?.order) {
      setSortBy(String(s.field))
      setSortOrder(s.order === 'ascend' ? 'asc' : 'desc')
    } else {
      setSortBy(undefined)
    }
    setPage(1)
  }

  const columns = BASE_COLUMNS.map(col => {
    const key = (col.dataIndex as string) ?? String(col.title)
    const width = colWidths[key] ?? (col.width as number)
    return {
      ...col,
      width,
      onHeaderCell: () => ({
        width,
        onResize: (w: number) => setColWidths(prev => ({ ...prev, [key]: w })),
      }),
    }
  })

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
        <Row gutter={[8, 8]} style={{ marginBottom: 16 }} align="middle">
          <Col span={4}>
            <Select placeholder="选择文件" allowClear style={{ width: '100%' }} onChange={v => updateFilter('file_id', v)}>
              {(filesData ?? []).map((f: { id: number; filename: string }) => (
                <Select.Option key={f.id} value={f.id}>{f.filename}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={3}>
            <Select placeholder="平台" allowClear style={{ width: '100%' }} onChange={v => updateFilter('platform', v)}>
              {(filterOptions?.platforms ?? []).map((p: string) => (
                <Select.Option key={p} value={p}>{p}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={3}>
            <Select placeholder="月份" allowClear style={{ width: '100%' }} onChange={v => updateFilter('month', v)}>
              {(filterOptions?.months ?? []).map((m: number) => (
                <Select.Option key={m} value={m}>{m}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col span={4}>
            <Input placeholder="搜索标准品牌" allowClear onChange={e => updateFilter('brand_std', e.target.value)} />
          </Col>
          <Col span={4}>
            <Input placeholder="搜索品牌原始值" allowClear onChange={e => updateFilter('brand_raw', e.target.value)} />
          </Col>
          <Col span={4}>
            <Input placeholder="搜索商品名称" allowClear onChange={e => updateFilter('item_name', e.target.value)} />
          </Col>
          <Col span={3}>
            <InputNumber
              min={0}
              precision={2}
              placeholder="最低价"
              value={filters.price_min as number | undefined}
              style={{ width: '100%' }}
              onChange={value => updatePriceFilter('price_min', value)}
            />
          </Col>
          <Col span={3}>
            <InputNumber
              min={0}
              precision={2}
              placeholder="最高价"
              value={filters.price_max as number | undefined}
              style={{ width: '100%' }}
              onChange={value => updatePriceFilter('price_max', value)}
            />
          </Col>
          <Col span={2} style={{ textAlign: 'right' }}>
            <Button onClick={handleExport} loading={exporting}>导出 Excel</Button>
          </Col>
        </Row>

        <Table
          dataSource={tableData?.items ?? []}
          columns={columns}
          components={{ header: { cell: ResizableTitle } }}
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
