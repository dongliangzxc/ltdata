import { useState } from 'react'
import {
  Card, Checkbox, Switch, Button, Table, Tag, Modal, Row, Col,
  Space, Typography, message, Alert, Statistic, Select
} from 'antd'
import { PlayCircleOutlined, EyeOutlined, AimOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import {
  listUploadFiles, listCleanJobs, runCleanJob, previewCleanJob,
  listDispatchBatches, getDispatchBatchStats
} from '../../services/api'

const { Text } = Typography

const jobColumns = (onPreview: (id: number) => void, onMatch: (id: number) => void) => [
  { title: 'ID', dataIndex: 'id', width: 60 },
  {
    title: '文件', dataIndex: 'file_ids', width: 120,
    render: (v: number[]) => v?.map(id => <Tag key={id}>文件#{id}</Tag>)
  },
  { title: '输入行', dataIndex: 'row_in', width: 80 },
  { title: '输出行', dataIndex: 'row_out', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => <Tag color={v === 'done' ? 'green' : v === 'error' ? 'red' : 'orange'}>{v}</Tag>
  },
  {
    title: '时间', dataIndex: 'created_at',
    render: (v: string) => new Date(v).toLocaleString('zh-CN')
  },
  {
    title: '操作', width: 140,
    render: (_: unknown, row: { id: number; status: string }) => (
      <Space size={4}>
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => onPreview(row.id)}>预览</Button>
        {row.status === 'done' && (
          <Button type="link" icon={<AimOutlined />} size="small" onClick={() => onMatch(row.id)}>执行匹配</Button>
        )}
      </Space>
    )
  },
]

const previewCols = [
  { title: '平台', dataIndex: 'platform', width: 90 },
  { title: '月份', dataIndex: 'month', width: 90 },
  { title: '品牌', dataIndex: 'brand_std', width: 110 },
  { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true },
  { title: '销量', dataIndex: 'sales_qty', width: 80 },
  {
    title: '销售额', dataIndex: 'sales_amount', width: 110,
    render: (v: number) => v != null ? `¥${Number(v).toLocaleString()}` : '-'
  },
]

export default function CleanPage() {
  const navigate = useNavigate()
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([])
  const [dedup, setDedup] = useState(true)
  const [running, setRunning] = useState(false)
  const [previewJobId, setPreviewJobId] = useState<number | null>(null)
  const [previewPage, setPreviewPage] = useState(1)
  const [dispatchBatchId, setDispatchBatchId] = useState<number | null>(null)
  const [dispatchCategoryCode, setDispatchCategoryCode] = useState<string | undefined>()
  const [categoryOptions, setCategoryOptions] = useState<{ value: string; label: string }[]>([])

  const { data: filesData } = useRequest(() => listUploadFiles().then(r => r.data))
  const { data: jobsData, refresh: refreshJobs } = useRequest(() => listCleanJobs().then(r => r.data))

  const { data: previewData, loading: previewLoading } = useRequest(
    () => previewCleanJob(previewJobId!, { page: previewPage, page_size: 20 }).then(r => r.data),
    { ready: previewJobId != null, refreshDeps: [previewJobId, previewPage] }
  )

  const handleFileChange = async (ids: number[]) => {
    setSelectedFileIds(ids)
    setDispatchCategoryCode(undefined)
    setCategoryOptions([])
    setDispatchBatchId(null)
    if (ids.length === 1) {
      try {
        const batchRes = await listDispatchBatches({ file_id: ids[0] })
        const doneBatch = (batchRes.data as Array<{ id: number; status: string; file_id: number }>)
          .filter(b => b.status === 'done')
          .reduce<{ id: number; status: string; file_id: number } | null>(
            (best, b) => (best === null || b.id > best.id ? b : best),
            null,
          )
        if (doneBatch) {
          setDispatchBatchId(doneBatch.id)
          const statsRes = await getDispatchBatchStats(doneBatch.id)
          const cats = statsRes.data.categories as Array<{ category_code: string; count: number }>
          setCategoryOptions(cats.map(c => ({
            value: c.category_code,
            label: `${c.category_code}（${c.count.toLocaleString()} 条）`,
          })))
        }
      } catch {
        // ignore errors — just don't show category selector
      }
    }
  }

  const handleRun = async () => {
    if (!selectedFileIds.length) { message.warning('请先选择文件'); return }
    setRunning(true)
    try {
      await runCleanJob({
        file_ids: selectedFileIds,
        rules: { dedup },
        ...(dispatchBatchId && dispatchCategoryCode
          ? { dispatch_batch_id: dispatchBatchId, dispatch_category_code: dispatchCategoryCode }
          : {}),
      })
      message.success('清洗完成')
      refreshJobs()
    } finally {
      setRunning(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 0 }}
        message="数据清洗说明"
        description={
          <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
            <li><b>去重</b>：同一商品（相同 item_id）同月份同店铺只保留第一条</li>
            <li><b>品牌标准化</b>：自动将 brand_std 为空的记录用原始品牌名补全</li>
            <li>清洗结果独立保存，不影响原始数据，可反复清洗</li>
            <li>清洗完成后，点击"执行匹配"前往匹配确认页面进行型号匹配</li>
          </ul>
        }
      />
      <Card title="清洗配置">
        <Row gutter={24}>
          <Col span={12}>
            <Text strong>选择文件（可多选）</Text>
            <Checkbox.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}
              value={selectedFileIds}
              onChange={v => handleFileChange(v as number[])}
            >
              {(filesData ?? []).map((f: { id: number; filename: string; platform: string; row_count: number }) => (
                <Checkbox key={f.id} value={f.id}>
                  <Space>
                    <Tag color="blue">{f.platform}</Tag>
                    {f.filename}
                    <Text type="secondary">({f.row_count} 条)</Text>
                  </Space>
                </Checkbox>
              ))}
            </Checkbox.Group>
          </Col>
          <Col span={12}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <div>
                <Space>
                  <Text strong>去重</Text>
                  <Switch checked={dedup} onChange={setDedup} />
                  <Text type="secondary">（同 item_id + 月份 + 店铺保留第一条）</Text>
                </Space>
              </div>
              {categoryOptions.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <Text strong>按品类过滤（可选）</Text>
                  <Select
                    placeholder="选择品类（不选=全量清洗）"
                    allowClear
                    style={{ width: '100%', marginTop: 8 }}
                    options={categoryOptions}
                    value={dispatchCategoryCode}
                    onChange={v => setDispatchCategoryCode(v)}
                  />
                </div>
              )}
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleRun}
                loading={running}
                size="large"
              >
                开始清洗
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card title="清洗任务历史">
        {(jobsData ?? []).length > 0 && (
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {[jobsData[0]].map((j: { id: number; row_in: number; row_out: number; row_filtered?: number }) => (
              <>
                <Col span={6}><Statistic title="最近一次：输入行数" value={j.row_in} /></Col>
                <Col span={6}><Statistic title="清洗后输出行数" value={j.row_out} valueStyle={{ color: '#3f8600' }} /></Col>
                <Col span={6}><Statistic title="过滤掉" value={j.row_in - j.row_out} valueStyle={{ color: '#cf1322' }} /></Col>
                <Col span={6}>
                  <Statistic
                    title="被过滤（干扰词）"
                    value={j.row_filtered ?? 0}
                    valueStyle={{ color: '#d48806' }}
                    suffix={
                      (j.row_filtered ?? 0) > 0
                        ? <a style={{ fontSize: 12, marginLeft: 4 }}
                            onClick={() => window.open(`/rules?tab=filtered&job_id=${j.id}`, '_blank')}>
                            查看 →
                          </a>
                        : undefined
                    }
                  />
                </Col>
              </>
            ))}
          </Row>
        )}
        <Table
          dataSource={jobsData ?? []}
          columns={jobColumns(
            id => { setPreviewJobId(id); setPreviewPage(1) },
            id => navigate(`/match?job_id=${id}`)
          )}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title={`清洗结果预览（任务 #${previewJobId}）`}
        open={previewJobId != null}
        onCancel={() => setPreviewJobId(null)}
        footer={null}
        width={1000}
      >
        <Table
          dataSource={previewData?.items ?? []}
          columns={previewCols}
          rowKey="id"
          size="small"
          loading={previewLoading}
          scroll={{ x: 800 }}
          pagination={{
            current: previewPage,
            pageSize: 20,
            total: previewData?.total ?? 0,
            onChange: setPreviewPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Modal>
    </Space>
  )
}
