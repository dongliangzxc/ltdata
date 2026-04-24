import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/Layout'
import UploadPage from './pages/Upload'
import DataListPage from './pages/DataList'
import CleanPage from './pages/Clean'
import MatchPage from './pages/Match'
import ExportPage from './pages/Export'
import MetadataPage from './pages/Metadata'
import ModelsPage from './pages/Models'

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/upload" replace />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/rawdata" element={<DataListPage />} />
          <Route path="/clean" element={<CleanPage />} />
          <Route path="/match" element={<MatchPage />} />
          <Route path="/export" element={<ExportPage />} />
          <Route path="/metadata" element={<MetadataPage />} />
          <Route path="/models" element={<ModelsPage />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  )
}
