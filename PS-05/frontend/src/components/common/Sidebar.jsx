import React from 'react';
import {
  LayoutDashboard,
  GitPullRequest,
  Cpu,
  FileDiff,
  ShieldCheck,
  Terminal,
  Activity,
  Layers,
  Sparkles
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';

export default function Sidebar({ currentTab, setCurrentTab }) {
  const { activeSession, healthStatus } = useSession();

  const navItems = [
    {
      id: 'overview',
      label: 'Overview',
      badge: 'Dashboard',
      icon: LayoutDashboard,
      description: 'Pipeline & System Health',
    },
    {
      id: 'intake',
      label: 'Issue & Sandbox',
      badge: 'Phase 2–3',
      icon: GitPullRequest,
      description: 'Intake, Clone & Reproduce',
    },
    {
      id: 'repair',
      label: 'Repair Workspace',
      badge: 'Phase 4 & 6B',
      icon: Cpu,
      description: 'Localize & Bounded Repair Loop',
      highlight: true,
    },
    {
      id: 'patch',
      label: 'Patch & Verification',
      badge: 'Phase 5A–5B',
      icon: FileDiff,
      description: 'Diff Review & Docker Test Verify',
    },
    {
      id: 'system',
      label: 'Security & Docker',
      badge: 'Controls',
      icon: ShieldCheck,
      description: 'Sandbox Verification & Enforcements',
    },
  ];

  return (
    <aside className="w-64 border-r border-slate-800 bg-[#070B14]/95 flex flex-col justify-between p-4 flex-shrink-0 z-20">
      <div className="space-y-6">
        {/* Navigation Section */}
        <div>
          <div className="px-3 pb-2 text-[10px] font-mono uppercase tracking-wider text-slate-500 font-semibold">
            Command Center
          </div>
          <nav className="space-y-1.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setCurrentTab(item.id)}
                  className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-xl text-left transition-all group relative ${
                    isActive
                      ? 'bg-gradient-to-r from-cyan-950/60 to-slate-900 border border-cyan-800/60 text-cyan-300 shadow-glow-cyan'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent'
                  }`}
                >
                  <div className={`p-1.5 rounded-lg mt-0.5 ${isActive ? 'bg-cyan-500/20 text-cyan-400' : 'bg-slate-800 text-slate-400 group-hover:text-slate-200'}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold tracking-tight">{item.label}</span>
                      <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${isActive ? 'bg-cyan-900/60 text-cyan-300' : 'bg-slate-800 text-slate-500'}`}>
                        {item.badge}
                      </span>
                    </div>
                    <p className="text-[10px] text-slate-500 truncate mt-0.5">{item.description}</p>
                  </div>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Active Session Card in Sidebar */}
        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 font-medium">Session Status</span>
            <span className="flex h-2 w-2 rounded-full bg-cyan-400 animate-pulse"></span>
          </div>
          {activeSession ? (
            <div className="space-y-1 text-xs">
              <div className="flex justify-between items-center text-slate-300 font-mono">
                <span className="text-slate-500">ID:</span>
                <span className="text-cyan-300 font-semibold">{activeSession.session_id}</span>
              </div>
              <div className="flex justify-between items-center text-slate-300">
                <span className="text-slate-500">State:</span>
                <span className="font-mono uppercase text-[11px] text-slate-200">{activeSession.state}</span>
              </div>
              <div className="flex justify-between items-center text-slate-300">
                <span className="text-slate-500">Docker:</span>
                <span className={`text-[11px] font-semibold ${activeSession.docker_available ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {activeSession.docker_available ? 'AVAILABLE' : 'OFFLINE'}
                </span>
              </div>
            </div>
          ) : (
            <div className="text-[11px] text-slate-500 font-mono">
              No active session loaded. Start an issue intake or select a session.
            </div>
          )}
        </div>
      </div>

      {/* Footer Info */}
      <div className="pt-4 border-t border-slate-800/80 text-[11px] text-slate-500 flex flex-col gap-1 font-mono">
        <div className="flex justify-between items-center">
          <span>Engine:</span>
          <span className="text-slate-400">PS-05 v0.1.0</span>
        </div>
        <div className="flex justify-between items-center">
          <span>Docker Sandbox:</span>
          <span className="text-emerald-400">Isolated (ro)</span>
        </div>
      </div>
    </aside>
  );
}
