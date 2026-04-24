import { Navigate, Outlet, useLocation } from 'react-router-dom'

export default function PrivateRoute() {
  const token = localStorage.getItem('token')
  const location = useLocation()
  if (!token) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  return <Outlet />
}
