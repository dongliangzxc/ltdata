import type { PermissionKey, UserProfile } from '../services/api'

export type { PermissionKey }

export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  data_management: '数据管理',
  processing_workbench: '处理工作台',
  product_management: '成品管理',
}

const PATH_PERMISSION_PREFIXES: Array<[string, PermissionKey]> = [
  ['/upload', 'data_management'],
  ['/dispatch', 'data_management'],
  ['/rawdata', 'data_management'],
  ['/categories', 'data_management'],
  ['/metadata', 'processing_workbench'],
  ['/models', 'processing_workbench'],
  ['/brands', 'processing_workbench'],
  ['/url-mappings', 'processing_workbench'],
  ['/historical', 'processing_workbench'],
  ['/clean', 'processing_workbench'],
  ['/data-adjustment', 'processing_workbench'],
  ['/rules', 'processing_workbench'],
  ['/match', 'processing_workbench'],
  ['/match-results', 'processing_workbench'],
  ['/dashboard', 'product_management'],
  ['/export', 'product_management'],
  ['/workbench', 'processing_workbench'],
]

export function hasPermission(user: UserProfile | null, permission?: PermissionKey) {
  if (!permission) return true
  if (!user) return false
  if (user.is_admin === 1) return true
  return user.permissions.includes(permission)
}

export function canAccessPath(user: UserProfile | null, path: string) {
  if (!user) return false
  if (path === '/manual') return true
  if (path === '/users') return user.is_admin === 1
  const match = PATH_PERMISSION_PREFIXES.find(([prefix]) => path === prefix || path.startsWith(`${prefix}/`))
  if (!match) return true
  return hasPermission(user, match[1])
}

export function getDefaultPath(user: UserProfile | null) {
  if (!user) return '/login'
  if (hasPermission(user, 'data_management')) return '/upload'
  if (hasPermission(user, 'processing_workbench')) return '/metadata'
  if (hasPermission(user, 'product_management')) return '/dashboard'
  return '/manual'
}
