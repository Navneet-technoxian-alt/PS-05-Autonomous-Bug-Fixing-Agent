import React from 'react';
import {
  Shield,
  Cpu,
  GitPullRequest,
  FileCheck2,
  Layers,
  ExternalLink,
  ArrowRight,
  Clock,
  FolderGit2,
  AlertTriangle,
  CheckCircle2,
  Lock,
  Boxes
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import StatusBadge from '../common/StatusBadge';

export default function OverviewView({ setCurrentTab }) {
  const { healthStatus, activeSession, sessionList, setActiveSessionId } = useSession();

  const pipelineSteps = [
    {
      num: '01',
      title: 'Issue Intake',
      desc: 'Validate public GitHub issue URL and extract stack trace & error signatures.',
      badge: 'Phase 2',
      tab: 'intake',
    },
    {
      num: '02',
      title: 'Sandbox & Reproduce',
      desc: 'Clone to disposable directory and execute candidate test in restricted Docker container.',
      badge: 'Phase 3',
      tab: 'intake',
    },
    {
      num: '03',
      title: 'Bug Localization',
      desc: 'Deterministic ranking of suspected files and functions from failure evidence.',
      badge: 'Phase 4',
      tab: 'repair',
    },
    {
      num: '04',
      title: 'Patch Synthesis',
      desc: 'Generate reviewable unified diff proposals via deterministic mock or AI provider.',
      badge: 'Phase 4 & 6A',
      tab: 'patch',
    },
    {
      num: '05',
      title: 'Isolated Verification',
      desc: 'Apply diff in-memory and verify fix inside read-only Docker container.',
      badge: 'Phase 5A–5B',
      tab: 'patch',
    },
    {
      num: '06',
      title: 'Bounded Repair Loop',
      desc: 'Autonomous multi-attempt repair loop with rollback & dirty-session containment.',
      badge: 'Phase 6B',
      tab: 'repair',
    },
  ];

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Top Banner / Welcome */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-r from-slate-900/90 via-[#0C1222] to-cyan-950/40 p-6 md:p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="relative z-10 max-w-3xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-mono font-medium mb-4">
            <Shield className="w-3.5 h-3.5" />
            <span>Autonomous Software Repair & Security Verification</span>
          </div>
          <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight leading-tight">
            Deterministic Bug Reproduction & Sandboxed Autonomous Repair
          </h2>
          <p className="mt-3 text-slate-300 text-sm md:text-base leading-relaxed">
            PS-05 provides end-to-end vulnerability and defect mitigation. Code is cloned into disposable workspaces,
            reproduced strictly in security-hardened Docker containers, and repaired through bounded, rollbacked patch iterations.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              onClick={() => setCurrentTab('intake')}
              className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-semibold text-xs tracking-wide shadow-glow-cyan flex items-center gap-2 transition"
            >
              <span>Start Issue Intake</span>
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => setCurrentTab('repair')}
              className="px-5 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-200 font-semibold text-xs border border-slate-700/80 hover:border-slate-600 transition flex items-center gap-2"
            >
              <Cpu className="w-4 h-4 text-cyan-400" />
              <span>Repair Loop Workspace</span>
            </button>
          </div>
        </div>
      </div>

      {/* Backend Status & System Telemetry Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Backend Connectivity Card */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">FastAPI Backend</span>
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold ${
              healthStatus.connected ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${healthStatus.connected ? 'bg-emerald-400' : 'bg-rose-400'}`}></span>
              {healthStatus.connected ? 'HEALTHY' : 'UNREACHABLE'}
            </span>
          </div>
          <div className="text-xl font-bold text-slate-100 font-mono">
            {healthStatus.connected ? 'v' + (healthStatus.data?.version || '0.1.0') : 'Offline'}
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            {healthStatus.connected
              ? `Operational status verified via /health with ${healthStatus.data?.latency || 0}ms roundtrip response time.`
              : 'Backend server not responding at configured API base URL.'}
          </p>
        </div>

        {/* Docker Isolation Engine Card */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Docker Sandbox</span>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
              <Lock className="w-3 h-3" />
              RESTRICTED
            </span>
          </div>
          <div className="text-xl font-bold text-slate-100 font-mono">
            --network=none
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Containers run with all capabilities dropped (<code className="text-cyan-300">--cap-drop=ALL</code>), non-root user (<code className="text-cyan-300">1000:1000</code>), and read-only mounts.
          </p>
        </div>

        {/* Active Session Context Card */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Active Session</span>
            {activeSession ? (
              <StatusBadge status={activeSession.state} size="sm" />
            ) : (
              <span className="text-[10px] font-mono text-slate-500">IDLE</span>
            )}
          </div>
          <div className="text-xl font-bold text-slate-100 font-mono truncate">
            {activeSession ? activeSession.session_id : 'No Session Selected'}
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            {activeSession
              ? `Repository: ${activeSession.repo_url.replace('https://github.com/', '')}`
              : 'Load or prepare a session in Issue & Sandbox to begin reproduction.'}
          </p>
        </div>
      </div>

      {/* Pipeline Architecture Flow */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
            <Layers className="w-4 h-4 text-cyan-400" />
            <span>Autonomous Repair Workflow Pipeline</span>
          </h3>
          <span className="text-xs text-slate-500 font-mono">Click a phase to navigate</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {pipelineSteps.map((step) => (
            <div
              key={step.num}
              onClick={() => setCurrentTab(step.tab)}
              className="p-5 rounded-xl border border-slate-800 bg-[#090D1A] hover:bg-slate-900/80 hover:border-cyan-800/60 cursor-pointer transition-all duration-200 group relative overflow-hidden"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-2xl font-black font-mono text-slate-700 group-hover:text-cyan-400/50 transition">
                  {step.num}
                </span>
                <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-400 group-hover:bg-cyan-950/80 group-hover:text-cyan-300 border border-slate-700/60 transition">
                  {step.badge}
                </span>
              </div>
              <h4 className="text-sm font-bold text-slate-200 group-hover:text-cyan-300 transition">
                {step.title}
              </h4>
              <p className="mt-1.5 text-xs text-slate-400 leading-relaxed">
                {step.desc}
              </p>
              <div className="mt-4 flex items-center gap-1.5 text-[11px] font-medium text-cyan-400/80 opacity-0 group-hover:opacity-100 transition">
                <span>Open module</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Real Sessions Observed In Memory */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
            <FolderGit2 className="w-4 h-4 text-cyan-400" />
            <span>Managed Sandbox Sessions</span>
          </h3>
          <span className="text-xs text-slate-500 font-mono">
            {sessionList.length} session{sessionList.length === 1 ? '' : 's'} recorded in runtime state
          </span>
        </div>

        {sessionList.length > 0 ? (
          <div className="border border-slate-800 rounded-xl bg-slate-900/60 overflow-hidden divide-y divide-slate-800/60">
            {sessionList.map((sess) => (
              <div
                key={sess.session_id}
                className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-slate-800/30 transition"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-sm font-semibold text-cyan-300">
                      {sess.session_id}
                    </span>
                    <StatusBadge status={sess.state} size="sm" />
                    {sess.is_dirty && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                        DIRTY
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 flex items-center gap-4">
                    <span>Repo: {sess.repo_url}</span>
                    {sess.commit_sha && (
                      <span className="font-mono text-slate-500">SHA: {sess.commit_sha.substring(0, 7)}</span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setActiveSessionId(sess.session_id);
                      setCurrentTab('repair');
                    }}
                    className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-cyan-600/20 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-600/30 transition"
                  >
                    Open in Repair
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl bg-slate-950/40 text-slate-500 text-xs font-mono">
            No active sessions yet. Prepare a repository workspace in "Issue & Sandbox" or enter an existing session ID.
          </div>
        )}
      </div>
    </div>
  );
}
