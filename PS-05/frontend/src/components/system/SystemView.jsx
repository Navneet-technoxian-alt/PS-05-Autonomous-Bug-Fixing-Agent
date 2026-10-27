import React, { useState } from 'react';
import {
  ShieldCheck,
  Lock,
  Activity,
  Server,
  Cpu,
  Terminal,
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Layers,
  KeyRound,
  RotateCcw
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import { fetchHealth } from '../../api/client';

export default function SystemView() {
  const { healthStatus, activeSession } = useSession();
  const [testingHealth, setTestingHealth] = useState(false);
  const [healthData, setHealthData] = useState(healthStatus.data);

  const handleTestHealth = async () => {
    setTestingHealth(true);
    try {
      const data = await fetchHealth();
      setHealthData(data);
    } catch (err) {
      console.error(err);
    } finally {
      setTestingHealth(false);
    }
  };

  const securityControls = [
    {
      name: 'Network Isolation',
      flag: '--network=none',
      status: 'Enforced',
      desc: 'Prevents outbound command-and-control, credential exfiltration, and socket leakage from container.',
    },
    {
      name: 'Dropped Linux Capabilities',
      flag: '--cap-drop=ALL',
      status: 'Enforced',
      desc: 'Strips all root privileges, kernel capabilities, raw network access, and namespace escapes.',
    },
    {
      name: 'Non-Root Container User',
      flag: '--user=1000:1000',
      status: 'Enforced',
      desc: 'Enforces unprivileged host execution. Code runs strictly under mapped UID/GID 1000:1000.',
    },
    {
      name: 'Read-Only Workspace Mount',
      flag: '-v <dir>:/workspace:ro',
      status: 'Enforced',
      desc: 'Verification tests mount the repository as read-only to ensure tests cannot mutate disk state.',
    },
    {
      name: 'Resource Bound Clamps',
      flag: '--memory=1g --cpus=1.0 --pids-limit=100',
      status: 'Enforced',
      desc: 'Strict limits on memory allocation, CPU time, and spawned thread/process counts.',
    },
    {
      name: 'Docker Socket Excluded',
      flag: 'Forbidden /var/run/docker.sock',
      status: 'Enforced',
      desc: 'Docker daemon socket is strictly prohibited from volume mounts to prevent container breakout.',
    },
    {
      name: 'Credential Protection',
      flag: 'Forbidden ~/.ssh, ~/.aws, ~/.docker',
      status: 'Enforced',
      desc: 'Host credential directories and environment tokens are blocked from prompt injection and mounts.',
    },
    {
      name: 'Sensitive File Modification Blocking',
      flag: 'Blocked .env, .git, *.sh, *.exe',
      status: 'Enforced',
      desc: 'PatchValidator strictly blocks patches targeting configuration, shell scripts, or git internals.',
    },
  ];

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Title */}
      <div>
        <h2 className="text-xl font-bold text-slate-100 tracking-tight flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-cyan-400" />
          <span>System Health & Docker Security Auditing</span>
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Inspect backend service telemetry, review active Docker sandbox boundary enforcement rules, and inspect security controls.
        </p>
      </div>

      {/* Backend Health Diagnostics Card */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className="w-5 h-5 text-cyan-400" />
            <h3 className="text-sm font-bold text-slate-100 tracking-tight">Backend Telemetry & Connectivity</h3>
          </div>
          <button
            onClick={handleTestHealth}
            disabled={testingHealth}
            className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono font-medium flex items-center gap-2 transition"
          >
            <RotateCcw className={`w-3.5 h-3.5 ${testingHealth ? 'animate-spin' : ''}`} />
            <span>Ping /health</span>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs font-mono">
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-1">
            <span className="text-slate-500 text-[10px] uppercase">Service Name</span>
            <div className="font-bold text-slate-100 truncate">
              {healthData?.service || 'PS-05 Agent'}
            </div>
          </div>
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-1">
            <span className="text-slate-500 text-[10px] uppercase">Status</span>
            <div className="font-bold text-emerald-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
              <span>{healthData?.status?.toUpperCase() || 'ONLINE'}</span>
            </div>
          </div>
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-1">
            <span className="text-slate-500 text-[10px] uppercase">Engine Version</span>
            <div className="font-bold text-cyan-300">
              v{healthData?.version || '0.1.0'}
            </div>
          </div>
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-1">
            <span className="text-slate-500 text-[10px] uppercase">Roundtrip Latency</span>
            <div className="font-bold text-slate-200">
              {healthData?.latency !== undefined ? `${healthData.latency} ms` : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* Mandatory Docker Security Enforcement Audit Grid */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-cyan-400" />
            <h3 className="text-sm font-bold text-slate-100 tracking-tight">
              Mandatory Docker Sandbox Security Constraints
            </h3>
          </div>
          <span className="text-[10px] font-mono uppercase bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded">
            8 / 8 Active
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {securityControls.map((ctrl, i) => (
            <div key={i} className="p-4 rounded-xl border border-slate-800/80 bg-slate-950/80 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200">{ctrl.name}</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  {ctrl.status}
                </span>
              </div>
              <div className="font-mono text-cyan-400 text-[11px] bg-slate-900/80 px-2 py-1 rounded border border-slate-800">
                {ctrl.flag}
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                {ctrl.desc}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* AI Provider & Secret Redaction Policy */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-bold text-slate-100 tracking-tight">
            Security & Credential Protection Policy
          </h3>
        </div>

        <div className="space-y-2 text-xs text-slate-300 leading-relaxed font-sans">
          <p>
            • <strong>No Client-Side Secrets</strong>: The frontend application does not store, accept, or process API keys or tokens in code or browser storage.
          </p>
          <p>
            • <strong>Fail-Closed Gatekeeper</strong>: If <code className="text-cyan-300 font-mono">AI_PROVIDER_API_KEY</code> is missing on the backend, AI requests fail closed with a structured <code className="text-rose-400 font-mono">BLOCKED</code> response without outbound requests.
          </p>
          <p>
            • <strong>Automatic Secret Redaction</strong>: All stack traces, candidate snippets, and error payloads pass through regex secret scrubbers before prompt construction.
          </p>
          <p>
            • <strong>Zero Host Execution</strong>: No project test command is ever run on the host system. Docker is the exclusive runtime execution boundary.
          </p>
        </div>
      </div>
    </div>
  );
}
