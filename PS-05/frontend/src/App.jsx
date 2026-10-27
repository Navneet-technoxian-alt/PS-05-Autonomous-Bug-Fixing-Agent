import React, { useState } from 'react';
import { SessionProvider, useSession } from './context/SessionContext';
import TopBar from './components/common/TopBar';
import Sidebar from './components/common/Sidebar';
import OverviewView from './components/overview/OverviewView';
import IntakeView from './components/intake/IntakeView';
import RepairView from './components/repair/RepairView';
import PatchView from './components/patch/PatchView';
import SystemView from './components/system/SystemView';
import { AlertCircle, RefreshCw } from 'lucide-react';

function DashboardContent() {
  const [currentTab, setCurrentTab] = useState('overview');
  const { healthStatus } = useSession();

  return (
    <div className="min-h-screen flex flex-col bg-[#070B14] text-slate-100">
      {/* Top Header */}
      <TopBar />

      {/* Backend Disconnected Warning Banner if offline */}
      {!healthStatus.connected && !healthStatus.checking && (
        <div className="bg-rose-500/15 border-b border-rose-500/30 px-6 py-2.5 flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>
              <strong>Backend Disconnected:</strong> Cannot reach FastAPI backend. Make sure the backend server is running (<code className="font-mono text-rose-200">python -m uvicorn app.main:app --reload</code>).
            </span>
          </div>
          <span className="font-mono text-[11px] text-rose-400/80 hidden md:block">
            Target: {import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'}
          </span>
        </div>
      )}

      {/* Main Container with Sidebar + Content */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />

        <main className="flex-1 overflow-y-auto p-6 md:p-8 max-w-7xl mx-auto w-full">
          {currentTab === 'overview' && <OverviewView setCurrentTab={setCurrentTab} />}
          {currentTab === 'intake' && <IntakeView setCurrentTab={setCurrentTab} />}
          {currentTab === 'repair' && <RepairView setCurrentTab={setCurrentTab} />}
          {currentTab === 'patch' && <PatchView setCurrentTab={setCurrentTab} />}
          {currentTab === 'system' && <SystemView setCurrentTab={setCurrentTab} />}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <SessionProvider>
      <DashboardContent />
    </SessionProvider>
  );
}
