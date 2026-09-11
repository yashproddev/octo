import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Overview from './pages/Overview'
import Upload from './pages/Upload'
import Mapping from './pages/Mapping'
import Results from './pages/Results'
import ResultDetail from './pages/ResultDetail'
import DecisionLog from './pages/DecisionLog'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Overview />} />
          <Route path="upload" element={<Upload />} />
          <Route path="runs/:runId/mapping" element={<Mapping />} />
          <Route path="reconciliation/:runId" element={<Results />} />
          <Route path="reconciliation/:runId/results/:resultId" element={<ResultDetail />} />
          <Route path="results/:resultId" element={<ResultDetail />} />
          <Route path="decisions" element={<DecisionLog />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
