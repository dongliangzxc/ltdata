import { useEffect, useState } from 'react'
import { fetchCategories } from '../services/api'

export interface CategoryOption {
  label: string
  value: string
}

export function useCategoryOptions(): { options: CategoryOption[]; loading: boolean } {
  const [options, setOptions] = useState<CategoryOption[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchCategories()
      .then((cats: { code: string; name: string }[]) => {
        setOptions(cats.map(c => ({ label: c.name, value: c.code })))
      })
      .finally(() => setLoading(false))
  }, [])

  return { options, loading }
}
