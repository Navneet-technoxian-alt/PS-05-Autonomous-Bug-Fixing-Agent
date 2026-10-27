import React, { useState } from 'react';
import {
  Shield,
  Activity,
  ExternalLink,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Zap,
  FolderGit2,
  Trash2
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import { resetDirtySession } from '../../api/client';
import StatusBadge from './StatusBadge';

export default function TopBar() {
  const {
    healthStatus,
    activeSessionId,
    activeSession,
    sessionList,
    setActiveSessionId,
    refreshActiveSession
  } = useSession();

  const [resettingDirty, setResettingDirty] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    if (activeSessionId) {
      await refreshActiveSession(activeSessionId);
    }
    setTimeout(() => setRefreshing(false), 500);
  };

  const handleResetDirty = async () => {
    if (!activeSessionId) return;
    setResettingDirty(true);
    try {
      await resetDirtySession({ session_id: activeSessionId });
      await refreshActiveSession(activeSessionId);
    } catch (err) {
      console.error('Failed to reset dirty session:', err);
    } finally {
      setResettingDirty(false);
    }
  };

  const backendUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

  return (
    <header className="h-16 border-b border-slate-800 bg-[#090D1A]/90 backdrop-blur-md px-6 flex items-center justify-between z-30 sticky top-0">
      {/* Left: Branding & Agent Title */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 via-sky-500 to-blue-600 p-0.5 shadow-glow-cyan flex items-center justify-center">
          <div className="w-full h-full bg-[#070B14] rounded-[10px] flex items-center justify-center">
            <Shield className="w-5 h-5 text-cyan-400" />
          </div>
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-bold text-slate-100 tracking-tight">PS-05</h1>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/60 text-cyan-400 font-semibold">
              Autonomous Agent
            </span>
          </div>
          <p className="text-[11px] text-slate-400 hidden sm:block">Bug Localization, Patch Synthesis & Isolated Docker Verification</p>
        </div>
      </div>

      {/* Center/Right: Session Selector & Health Status */}
      <div className="flex items-center gap-4">
        {/* Active Session Pill if any */}
        {activeSessionId && (
          <div className="hidden md:flex items-center gap-2 pl-3 pr-2 py-1 bg-slate-900 border border-slate-700/60 rounded-xl text-xs font-mono">
            <span className="text-slate-400 flex items-center gap-1.5">
              <FolderGit2 className="w-3.5 h-3.5 text-cyan-400" />
              <span>Session:</span>
            </span>
            <select
              value={activeSessionId}
              onChange={(e) => setActiveSessionId(e.target.value)}
              className="bg-transparent text-cyan-300 font-semibold focus:outline-none cursor-pointer text-xs"
            >
              {sessionList.map(s => (
                <option key={s.session_id} value={s.session_id} className="bg-slate-900 text-slate-200">
                  {s.session_id} ({s.state || 'active'})
                </option>
              ))}
              {!sessionList.some(s => s.session_id === activeSessionId) && (
                <option value={activeSessionId} className="bg-slate-900 text-slate-200">
                  {activeSessionId}
                </option>
              )}
            </select>

            {activeSession?.state && (
              <StatusBadge status={activeSession.state} size="sm" showIcon={false} />
            )}

            {/* Dirty workspace warning & reset button */}
            {activeSession?.is_dirty && (
              <button
                onClick={handleResetDirty}
                disabled={resettingDirty}
                title="Workspace is marked dirty from unverified patch. Click to reset."
                className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded-lg hover:bg-amber-500/30 transition"
              >
                <span>DIRTY</span>
                <Trash2 className="w-3 h-3" />
              </button>
            )}
          </div>
        )}

        {/* Backend Connectivity Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-slate-800 bg-slate-900/60 text-xs">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              {healthStatus.connected ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                </>
              ) : (
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500"></span>
              )}
            </span>
            <span className={`font-mono text-[11px] font-medium ${healthStatus.connected ? 'text-emerald-400' : 'text-rose-400'}`}>
              {healthStatus.connected ? 'BACKEND ONLINE' : 'DISCONNECTED'}
            </span>
          </div>

          {healthStatus.connected && healthStatus.data?.latency !== undefined && (
            <span className="text-[10px] text-slate-400 font-mono border-l border-slate-700 pl-2">
              {healthStatus.data.latency}ms
            </span>
          )}
        </div>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="p-2 text-slate-400 hover:text-cyan-400 hover:bg-slate-800/60 rounded-xl border border-slate-800 transition"
          title="Refresh active state & health"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-cyan-400' : ''}`} />
        </button>

        {/* API Docs Swagger Link */}
        <a
          href={`${backendUrl}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="hidden lg:flex items-center gap-1.5 text-xs text-slate-400 hover:text-cyan-300 px-3 py-1.5 rounded-xl hover:bg-slate-800/60 border border-transparent hover:border-slate-800 transition"
        >
          <span>FastAPI Docs</span>
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>
    </header>
  );
}
