import { localStorageColorSchemeManager, MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import { theme } from './theme';
import Channels from './pages/Channels';
import Dashboard from './pages/Dashboard';
import Logs from './pages/Logs';
import Onboarding from './pages/Onboarding';
import Run from './pages/Run';
import Settings from './pages/Settings';
import { api } from './api/client';

function AppRoutes() {
  const [configured, setConfigured] = useState<boolean | null>(null);

  async function checkConfig() {
    try {
      const s = await api.getConfigStatus();
      setConfigured(s.configured);
    } catch {
      setConfigured(false);
    }
  }

  useEffect(() => { checkConfig(); }, []);

  // Still loading
  if (configured === null) return null;

  // First run — show onboarding wizard full-screen, no sidebar
  if (!configured) {
    return <Onboarding onComplete={() => setConfigured(true)} />;
  }

  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/run" element={<Run />} />
        <Route path="/channels" element={<Channels />} />
        <Route path="/channels/:number" element={<Channels />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/logs" element={<Logs />} />
      </Routes>
    </AppLayout>
  );
}

const colorSchemeManager = localStorageColorSchemeManager({ key: 'programmarr-color-scheme' });

export default function App() {
  return (
    <MantineProvider theme={theme} colorSchemeManager={colorSchemeManager} defaultColorScheme="dark">
      <Notifications position="top-right" />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </MantineProvider>
  );
}
