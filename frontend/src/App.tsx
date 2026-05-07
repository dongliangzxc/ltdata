import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import AppLayout from './components/Layout'
import PrivateRoute from './components/PrivateRoute'
import LoginPage from './pages/Login'
import UploadPage from './pages/Upload'
import DataListPage from './pages/DataList'
import CleanPage from './pages/Clean'
import MatchPage from './pages/Match'
import ExportPage from './pages/Export'
import MetadataPage from './pages/Metadata'
import ModelsPage from './pages/Models'
import WorkbenchPage from './pages/Workbench'
import ManualPage from './pages/Manual'
import UrlMappingsPage from './pages/UrlMappings'
import RulesPage from './pages/Rules'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 登录页，不需要布局 */}
        <Route path="/login" element={<LoginPage />} />

        {/* 受保护的业务路由，统一 AppLayout */}
        <Route element={<PrivateRoute />}>
          <Route element={<AppLayout><Outlet /></AppLayout>}>
            <Route path="/" element={<Navigate to="/upload" replace />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/rawdata" element={<DataListPage />} />
            <Route path="/clean" element={<CleanPage />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/match" element={<MatchPage />} />
            <Route path="/export" element={<ExportPage />} />
            <Route path="/metadata" element={<MetadataPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/workbench" element={<WorkbenchPage />} />
            <Route path="/manual" element={<ManualPage />} />
            <Route path="/url-mappings" element={<UrlMappingsPage />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
