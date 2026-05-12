import { Select } from 'antd'
import { useEffect, useState } from 'react'
import { fetchCategories } from '../services/api'

interface Category {
  id: number
  code: string
  name: string
}

interface Props {
  value?: string
  onChange?: (value: string) => void
  placeholder?: string
  disabled?: boolean
  style?: React.CSSProperties
}

export default function CategorySelect({ value, onChange, placeholder = '请选择品类', disabled, style }: Props) {
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchCategories()
      .then(data => setCategories(data))
      .catch(() => setCategories([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Select
      showSearch
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      disabled={disabled}
      loading={loading}
      style={style}
      filterOption={(input, option) =>
        (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
      }
      options={categories.map(c => ({
        value: c.code,
        label: `${c.name} (${c.code})`,
      }))}
    />
  )
}
