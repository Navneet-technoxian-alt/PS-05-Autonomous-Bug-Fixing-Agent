import React, { useState } from 'react';
import {
  GitPullRequest,
  Search,
  Terminal,
  Play,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ShieldCheck,
  ExternalLink,
  ChevronRight,
  Boxes,
  HelpCircle
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import {
  analyzeIssue,
  prepareSandbox,
  reproduceBug,
  fetchSession,
  formatApiError
} from '../../api/client';
import StatusBadge from '../common/StatusBadge';

export default function IntakeView({ setCurrentTab }) {
  const {
    activeSessionId,
    setActiveSessionId,
    activeSession,
    registerNewSession,
    refreshActiveSession
  } = useSession();

  // Intake states
  const [issueUrl, setIssueUrl] = useState('https://github.com/psf/requests/issues/1234');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisError, setAnalysisError] = useState(null);

  // Prepare states
  const [commitSha, setCommitSha] = useState('');
  const [preparing, setPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState(null);

  // Reproduction states
  const [testCommand, setTestCommand] = useState('');
  const [expectedPattern, setExpectedPattern] = useState('');
  const [reproducing, setReproducing] = useState(false);
  const [reproError, setReproError] = useState(null);

  // Manual lookup state
  const [lookupId, setLookupId] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setAnalyzing(true);
    setAnalysisError(null);
    setAnalysisResult(null);
    try {
      const data = await analyzeIssue(issueUrl);
      setAnalysisResult(data.issue);
    } catch (err) {
      setAnalysisError(formatApiError(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const handlePrepare = async () => {
    setPreparing(true);
    setPrepareError(null);
    try {
      const data = await prepareSandbox({
        issue_url: issueUrl,
        commit_sha: commitSha || undefined,
      });
      registerNewSession(data);
      if (data.candidate_test_commands?.length > 0) {
        setTestCommand(data.candidate_test_commands[0]);
      }
    } catch (err) {
      setPrepareError(formatApiError(err));
    } finally {
      setPreparing(false);
    }
  };

  const handleReproduce = async (e) => {
    e.preventDefault();
    if (!activeSessionId) return;
    setReproducing(true);
    setReproError(null);
    try {
      const data = await reproduceBug({
        session_id: activeSessionId,
        test_command: testCommand || undefined,
        expected_failure_pattern: expectedPattern || undefined,
      });
      registerNewSession(data);
    } catch (err) {
      setReproError(formatApiError(err));
    } finally {
      setReproducing(false);
    }
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!lookupId.trim()) return;
    setLookupLoading(true);
    setLookupError(null);
    try {
      const data = await fetchSession(lookupId.trim());
      registerNewSession(data);
      if (data.candidate_test_commands?.length > 0) {
        setTestCommand(data.candidate_test_commands[0]);
      }
      setLookupId('');
    } catch (err) {
      setLookupError(formatApiError(err));
    } finally {
      setLookupLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100 tracking-tight flex items-center gap-2">
          <GitPullRequest className="w-5 h-5 text-cyan-400" />
          <span>Issue Intake & Sandbox Reproduction</span>
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Intake public GitHub issues, provision disposable workspace directories, and execute containerized bug reproduction.
        </p>
      </div>

      {/* Grid: Issue Intake & Session Lookup */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Issue Analysis Form (2 cols) */}
        <div className="lg:col-span-2 p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-200 tracking-tight flex items-center gap-2">
              <Search className="w-4 h-4 text-cyan-400" />
              <span>Phase 2: GitHub Issue Intake</span>
            </h3>
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
              POST /issues/analyze
            </span>
          </div>

          <form onSubmit={handleAnalyze} className="space-y-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">
                Public GitHub Issue URL:
              </label>
              <div className="flex gap-2">
                <input
                  type="url"
                  required
                  value={issueUrl}
                  onChange={(e) => setIssueUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo/issues/123"
                  className="flex-1 bg-slate-950/80 border border-slate-700/80 rounded-xl px-4 py-2.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500 transition"
                />
                <button
                  type="submit"
                  disabled={analyzing}
                  className="px-5 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition flex items-center gap-2 disabled:opacity-50"
                >
                  {analyzing ? (
                    <>
                      <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>Analyzing...</span>
                    </>
                  ) : (
                    <span>Analyze</span>
                  )}
                </button>
              </div>
            </div>

            {analysisError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                {analysisError}
              </div>
            )}
          </form>

          {/* Analysis Result Card */}
          {analysisResult && (
            <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-3">
              <div className="flex items-start justify-between gap-3">
                <h4 className="text-sm font-bold text-slate-100">{analysisResult.title}</h4>
                <StatusBadge status={analysisResult.state} size="sm" showIcon={false} />
              </div>

              {analysisResult.body && (
                <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed font-sans bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80">
                  {analysisResult.body}
                </p>
              )}

              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 font-mono">
                <span className="flex items-center gap-1">
                  <span>Stack Trace Detected:</span>
                  <strong className={analysisResult.has_stack_trace ? 'text-emerald-400' : 'text-slate-500'}>
                    {analysisResult.has_stack_trace ? 'YES' : 'NO'}
                  </strong>
                </span>
                {analysisResult.potential_error_types?.length > 0 && (
                  <span className="flex items-center gap-1">
                    <span>Errors:</span>
                    <span className="text-cyan-300 font-semibold">{analysisResult.potential_error_types.join(', ')}</span>
                  </span>
                )}
              </div>

              {/* Action to Prepare Sandbox directly */}
              <div className="pt-2 flex items-center justify-between border-t border-slate-800">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={commitSha}
                    onChange={(e) => setCommitSha(e.target.value)}
                    placeholder="Optional Commit SHA to pin"
                    className="w-56 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-[11px] font-mono text-slate-300 focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <button
                  type="button"
                  onClick={handlePrepare}
                  disabled={preparing}
                  className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-semibold text-xs flex items-center gap-2 shadow-glow-cyan disabled:opacity-50 transition"
                >
                  {preparing ? (
                    <>
                      <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>Provisioning...</span>
                    </>
                  ) : (
                    <span>Provision Sandbox</span>
                  )}
                </button>
              </div>

              {prepareError && (
                <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                  {prepareError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Existing Session Lookup Card (1 col) */}
        <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-200 tracking-tight flex items-center gap-2">
              <Terminal className="w-4 h-4 text-cyan-400" />
              <span>Load Existing Session</span>
            </h3>
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
              GET /sandbox/:id
            </span>
          </div>
          <p className="text-xs text-slate-400">
            Have a previously provisioned session ID? Enter it below to inspect reproduction evidence or execute repair.
          </p>

          <form onSubmit={handleLookup} className="space-y-3">
            <div>
              <input
                type="text"
                required
                value={lookupId}
                onChange={(e) => setLookupId(e.target.value)}
                placeholder="Session ID (e.g. sess-abc12345)"
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500 transition"
              />
            </div>
            <button
              type="submit"
              disabled={lookupLoading}
              className="w-full px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-xs border border-slate-700 transition flex items-center justify-center gap-2"
            >
              {lookupLoading ? 'Loading...' : 'Load Session Context'}
            </button>
            {lookupError && (
              <div className="p-2.5 bg-rose-500/10 border border-rose-500/30 rounded-lg text-xs text-rose-300">
                {lookupError}
              </div>
            )}
          </form>

          {activeSession && (
            <div className="mt-4 p-3.5 bg-slate-950/80 border border-slate-800/80 rounded-xl space-y-2 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Loaded:</span>
                <span className="text-cyan-300 font-bold">{activeSession.session_id}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Status:</span>
                <StatusBadge status={activeSession.state} size="sm" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Docker Available:</span>
                <span className={activeSession.docker_available ? 'text-emerald-400' : 'text-rose-400'}>
                  {activeSession.docker_available ? 'YES' : 'NO'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Phase 3 Bug Reproduction Runner */}
      {activeSession && (
        <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2">
              <Terminal className="w-4 h-4 text-cyan-400" />
              <span>Phase 3: Controlled Bug Reproduction (Session: {activeSession.session_id})</span>
            </h3>
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
              POST /sandbox/reproduce
            </span>
          </div>

          <form onSubmit={handleReproduce} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1.5">
                  Test Command:
                </label>
                <input
                  type="text"
                  required
                  value={testCommand}
                  onChange={(e) => setTestCommand(e.target.value)}
                  placeholder="pytest tests/test_failure.py"
                  className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                />
                {activeSession.candidate_test_commands?.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5 items-center">
                    <span className="text-[10px] text-slate-500">Candidates:</span>
                    {activeSession.candidate_test_commands.map((cmd) => (
                      <button
                        key={cmd}
                        type="button"
                        onClick={() => setTestCommand(cmd)}
                        className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-cyan-300 hover:bg-slate-700 transition"
                      >
                        {cmd}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1.5">
                  Expected Failure Pattern:
                </label>
                <input
                  type="text"
                  value={expectedPattern}
                  onChange={(e) => setExpectedPattern(e.target.value)}
                  placeholder="e.g. ZeroDivisionError or TimeoutError"
                  className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                />
                <span className="text-[10px] text-slate-500 block mt-1">
                  Required to empirically confirm the defect reproduces in Docker.
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-slate-400 font-mono">
                Security: Runs strictly inside Docker with <code className="text-cyan-400">--network=none</code> and dropped capabilities.
              </span>
              <button
                type="submit"
                disabled={reproducing}
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-semibold text-xs tracking-wide shadow-glow-cyan flex items-center gap-2 disabled:opacity-50 transition"
              >
                {reproducing ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Running in Docker...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Run Reproduction</span>
                  </>
                )}
              </button>
            </div>

            {reproError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                {reproError}
              </div>
            )}
          </form>

          {/* Reproduction Outcome Display */}
          {activeSession.reproduction_result && (
            <div className="p-5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-slate-400 uppercase font-semibold">Reproduction Evidence Result</span>
                <StatusBadge status={activeSession.reproduction_result.outcome} size="lg" />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                <div>
                  <span className="text-slate-500 block text-[10px]">Exit Code</span>
                  <span className="font-bold text-slate-200">{activeSession.reproduction_result.exit_code}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px]">Duration</span>
                  <span className="font-bold text-slate-200">{activeSession.reproduction_result.duration_ms}ms</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px]">Command</span>
                  <span className="font-bold text-slate-200 truncate block">{activeSession.reproduction_result.command}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px]">Failure Pattern</span>
                  <span className="font-bold text-cyan-300">{activeSession.expected_failure_pattern || 'None specified'}</span>
                </div>
              </div>

              {activeSession.reproduction_result.stderr && (
                <div>
                  <label className="block text-[11px] font-mono text-slate-400 mb-1">Standard Error Output:</label>
                  <pre className="p-3 bg-[#070B14] border border-slate-800 rounded-lg text-xs font-mono text-rose-300 overflow-x-auto max-h-48 leading-relaxed">
                    {activeSession.reproduction_result.stderr}
                  </pre>
                </div>
              )}

              {activeSession.reproduction_result.stdout && (
                <div>
                  <label className="block text-[11px] font-mono text-slate-400 mb-1">Standard Output:</label>
                  <pre className="p-3 bg-[#070B14] border border-slate-800 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto max-h-48 leading-relaxed">
                    {activeSession.reproduction_result.stdout}
                  </pre>
                </div>
              )}

              {/* Ready to Localize / Repair prompt */}
              <div className="pt-2 flex justify-end">
                <button
                  onClick={() => setCurrentTab('repair')}
                  className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs flex items-center gap-2 shadow-glow-cyan transition"
                >
                  <span>Proceed to Localization & Repair</span>
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
