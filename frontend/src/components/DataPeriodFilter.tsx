import { Select, Space } from 'antd'

export const WEEK_OPTIONS = [1, 2, 3, 4, 5].map(value => ({ value, label: `第${value}周` }))

export default function DataPeriodFilter({ value, week, onChange, upload = false }: {
  value: 'month' | 'week'
  week?: number
  onChange: (value: 'month' | 'week', week?: number) => void
  upload?: boolean
}) {
  return <Space wrap>
    <Select aria-label="数据粒度" value={value} style={{ width: 100 }}
      options={[{ value: 'month', label: '月度' }, { value: 'week', label: '周度' }]}
      onChange={next => onChange(next, undefined)} />
    {value === 'week' && <Select aria-label={upload ? '统一指定周次' : '周次'} allowClear value={week}
      placeholder={upload ? '从文件周列读取' : '全部周次'} style={{ width: upload ? 170 : 130 }}
      options={WEEK_OPTIONS} onChange={next => onChange(value, next)} />}
  </Space>
}
