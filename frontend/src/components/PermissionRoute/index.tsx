import { Button, Result } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { canAccessPath, getDefaultPath } from '../../auth/permissions'
import { useAuth } from '../../auth/AuthContext'

export default function PermissionRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  if (!canAccessPath(user, location.pathname)) {
    return (
      <Result
        status="403"
        title="无权限访问"
        subTitle="当前账号没有访问该目录的权限。"
        extra={<Button type="primary" onClick={() => navigate(getDefaultPath(user), { replace: true })}>返回首页</Button>}
      />
    )
  }

  return children
}
