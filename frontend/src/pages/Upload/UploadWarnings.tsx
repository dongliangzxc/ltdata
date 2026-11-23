import { Alert, Modal, Space, Table, Tag, Typography } from 'antd'
import type { UploadValidationReport } from '../../services/api'

const { Text } = Typography

export function UploadWarningDetails({ reports }: { reports: UploadValidationReport[] }) {
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="warning"
        showIcon
        message="请核对以下数据，确认后仍可上传"
        description="继续上传后，缺失值和无法保存的数字将留空；异常月份可能影响按月查询。原文件会保留，方便后续核对。"
      />
      <Text type="secondary">表头为第 1 行；CSV 中含换行的字段按一条记录计。</Text>
      <div style={{ maxHeight: '50vh', overflowY: 'auto', width: '100%', paddingRight: 4 }}>
        {reports.map((report, index) => (
          <section key={index} style={{ marginBottom: index < reports.length - 1 ? 24 : 0 }}>
            <div style={{ marginBottom: 10 }}>
              <Text strong style={{ overflowWrap: 'anywhere' }}>{report.filename}</Text>
              <div style={{ marginTop: 4 }}>
                <Text type="secondary">共 {report.total_rows} 行，{report.affected_rows} 行存在 {report.issue_count} 处问题</Text>
              </div>
            </div>
            <Space size={[4, 6]} wrap style={{ marginBottom: 10 }}>
              {report.counts.missing_required > 0 && <Tag color="gold">必填值为空 {report.counts.missing_required}</Tag>}
              {report.counts.invalid_number > 0 && <Tag color="gold">数字异常 {report.counts.invalid_number}</Tag>}
              {report.counts.invalid_month > 0 && <Tag color="gold">月份异常 {report.counts.invalid_month}</Tag>}
            </Space>
            <Table<UploadValidationReport['samples'][number]>
              size="small"
              pagination={false}
              rowKey={(sample, sampleIndex) => `${sample.row}-${sample.field}-${sampleIndex}`}
              dataSource={report.samples}
              scroll={{ x: 570 }}
              columns={[
                { title: '行号', dataIndex: 'row', width: 65 },
                { title: '原始列', dataIndex: 'column', width: 120, render: (value: string | null) => value || '未映射' },
                {
                  title: '原始值', dataIndex: 'value', width: 145,
                  render: (value: string | null) => value == null || value.trim() === ''
                    ? <Text type="secondary">（空）</Text>
                    : <span style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{value}</span>,
                },
                { title: '问题', dataIndex: 'message', width: 240 },
              ]}
            />
            {report.truncated && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">仅展示前 {report.samples.length} 处问题，统计已覆盖文件全部数据。</Text>
              </div>
            )}
          </section>
        ))}
      </div>
    </Space>
  )
}

export function reviewUploadWarnings(reports: UploadValidationReport[]): Promise<boolean> {
  const warnings = reports.filter(report => report.issue_count > 0)
  if (warnings.length === 0) return Promise.resolve(true)
  return new Promise(resolve => {
    Modal.confirm({
      title: warnings.length === 1 ? '发现数据问题，是否继续上传？' : `${warnings.length} 个文件存在数据问题，是否继续上传？`,
      width: 820,
      style: { top: 24 },
      content: <UploadWarningDetails reports={warnings} />,
      okText: '仍然上传',
      cancelText: '返回检查',
      autoFocusButton: 'cancel',
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })
}
