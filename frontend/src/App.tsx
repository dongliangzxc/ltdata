import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import AppLayout from './components/Layout'
import PrivateRoute from './components/PrivateRoute'
import PermissionRoute from './components/PermissionRoute'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { getDefaultPath } from './auth/permissions'
import LoginPage from './pages/Login'
import UploadPage from './pages/Upload'
import DataListPage from './pages/DataList'
import CleanPage from './pages/Clean'
import MatchPage from './pages/Match'
import MatchResultsPage from './pages/MatchResults'
import DashboardPage from './pages/Dashboard'
import ExportPage from './pages/Export'
import MetadataPage from './pages/Metadata'
import ModelsPage from './pages/Models'
import WorkbenchPage from './pages/Workbench'
import ManualPage from './pages/Manual'
import UrlMappingsPage from './pages/UrlMappings'
import RulesPage from './pages/Rules'
import HistoricalPage from './pages/Historical'
import CategoriesPage from './pages/Categories'
import DispatchPage from './pages/Dispatch'
import BrandsPage from './pages/Brands'
import UsersPage from './pages/Users'

function DefaultRedirect() {
  const { user } = useAuth()
  return <Navigate to={getDefaultPath(user)} replace />
}

function ProtectedPage({ children }: { children: React.ReactNode }) {
  return <PermissionRoute>{children}</PermissionRoute>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
        {/* 登录页，不需要布局 */}
        <Route path="/login" element={<LoginPage />} />

        {/* 受保护的业务路由，统一 AppLayout */}
        <Route element={<PrivateRoute />}>
          <Route element={<AppLayout><Outlet /></AppLayout>}>
            <Route path="/" element={<DefaultRedirect />} />
            <Route path="/upload" element={<ProtectedPage><UploadPage /></ProtectedPage>} />
            <Route path="/rawdata" element={<ProtectedPage><DataListPage /></ProtectedPage>} />
            <Route path="/clean" element={<ProtectedPage><CleanPage /></ProtectedPage>} />
            <Route path="/data-adjustment" element={<Navigate to="/match-results" replace />} />
            <Route path="/rules" element={<ProtectedPage><RulesPage /></ProtectedPage>} />
            <Route path="/match" element={<ProtectedPage><MatchPage /></ProtectedPage>} />
            <Route path="/match-results" element={<ProtectedPage><MatchResultsPage /></ProtectedPage>} />
            <Route path="/dashboard" element={<ProtectedPage><DashboardPage /></ProtectedPage>} />
            <Route path="/export" element={<ProtectedPage><ExportPage /></ProtectedPage>} />
            <Route path="/metadata" element={<ProtectedPage><MetadataPage /></ProtectedPage>} />
            <Route path="/models" element={<ProtectedPage><ModelsPage /></ProtectedPage>} />
            <Route path="/workbench" element={<ProtectedPage><WorkbenchPage /></ProtectedPage>} />
            <Route path="/manual" element={<ProtectedPage><ManualPage /></ProtectedPage>} />
            <Route path="/url-mappings" element={<ProtectedPage><UrlMappingsPage /></ProtectedPage>} />
            <Route path="/categories" element={<ProtectedPage><CategoriesPage /></ProtectedPage>} />
            <Route path="/historical" element={<ProtectedPage><HistoricalPage /></ProtectedPage>} />
            <Route path="/dispatch" element={<ProtectedPage><DispatchPage /></ProtectedPage>} />
            <Route path="/brands" element={<ProtectedPage><BrandsPage /></ProtectedPage>} />
            <Route path="/users" element={<ProtectedPage><UsersPage /></ProtectedPage>} />
          </Route>
        </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
