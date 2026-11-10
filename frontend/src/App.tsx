import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './ErrorBoundary'
import { I18nProvider } from './i18n'
import { Shell } from './layout/Shell'
import { AdminPage } from './pages/AdminPage'
import { ChatPage } from './pages/ChatPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { ExplorerPage } from './pages/ExplorerPage'
import { SourcesPage } from './pages/SourcesPage'
import { AppProvider } from './state'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<ChatPage />} />
        <Route path="c/:conversationId" element={<ChatPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="explorer" element={<ExplorerPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="*" element={<ChatPage />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <I18nProvider>
        <AppProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </AppProvider>
      </I18nProvider>
    </ErrorBoundary>
  )
}
