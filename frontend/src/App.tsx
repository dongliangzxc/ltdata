import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/Layout'
import UploadPage from './pages/Upload'
import DataListPage from './pages/DataList'
import CleanPage from './pages/Clean'
import ExportPage from './pages/Export'

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/upload" replace />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/rawdata" element={<DataListPage />} />
          <Route path="/clean" element={<CleanPage />} />
          <Route path="/export" element={<ExportPage />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  )
}
