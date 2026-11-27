import { Select, Space } from 'antd'

export const WEEK_OPTIONS = [1, 2, 3, 4, 5].map(value => ({ value, label: `第${value}周` }))

export default function DataPeriodFilter({ value, week, onChange, upload = false, hasWeekColumn = false, weeks, onWeeksChange }: {
  value: 'month' | 'week'
  week?: number
  onChange: (value: 'month' | 'week', week?: number) => void
  upload?: boolean
  hasWeekColumn?: boolean
  weeks?: number[]
  onWeeksChange?: (weeks: number[]) => void
}) {
  return <Space wrap>
    <Select aria-label="数据粒度" value={value} style={{ width: 100 }}
      options={[{ value: 'month', label: '月度' }, { value: 'week', label: '周度' }]}
      onChange={next => { onChange(next, undefined); onWeeksChange?.([]) }} />
    {value === 'week' && (upload && hasWeekColumn ? <Select mode="multiple" aria-label="导入周次" allowClear
      value={weeks ?? []} maxTagCount={1} placeholder="全部周次（可多选）" style={{ width: 190 }}
      options={WEEK_OPTIONS} onChange={next => onWeeksChange?.([...next].sort((a, b) => a - b))} /> : <Select aria-label={upload ? '统一指定周次' : '周次'} allowClear value={week}
      placeholder={upload ? '从文件周列读取' : '全部周次'} style={{ width: upload ? 170 : 130 }}
      options={WEEK_OPTIONS} onChange={next => onChange(value, next)} />)}
  </Space>
}
