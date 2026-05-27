import { useState } from 'react'
import {
  Card, Button, Table, Tag, Modal, Row, Col,
  Space, Statistic
} from 'antd'
import { EyeOutlined, AimOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import {
  listCleanJobs, previewCleanJob,
} from '../../services/api'

const jobColumns = (onPreview: (id: number) => void, onMatch: (id: number) => void) => [
  { title: 'ID', dataIndex: 'id', width: 60 },
  {
    title: '清洗范围', dataIndex: 'scope_desc', width: 280,
    render: (v: string | null) => v || '-'
  },
  { title: '输入行', dataIndex: 'row_in', width: 80 },
  { title: '输出行', dataIndex: 'row_out', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => <Tag color={v === 'done' ? 'green' : v === 'error' ? 'red' : 'orange'}>{v}</Tag>
  },
  {
    title: '时间', dataIndex: 'created_at', width: 170,
    render: (v: string) => v || '-'
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
  const [previewJobId, setPreviewJobId] = useState<number | null>(null)
  const [previewPage, setPreviewPage] = useState(1)

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))

  const { data: previewData, loading: previewLoading } = useRequest(
    () => previewCleanJob(previewJobId!, { page: previewPage, page_size: 20 }).then(r => r.data),
    { ready: previewJobId != null, refreshDeps: [previewJobId, previewPage] }
  )

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="清洗历史">
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
