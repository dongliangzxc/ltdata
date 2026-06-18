import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuth } from '../../auth/AuthContext'

export default function PrivateRoute() {
  const { token, user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return <Spin fullscreen tip="加载登录状态..." />
  }

  if (!token || !user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return <Outlet />
}
