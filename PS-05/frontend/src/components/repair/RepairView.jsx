import React, { useState, useEffect } from 'react';
import {
  Cpu,
  Search,
  Play,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  Clock,
  FileCode,
  RotateCcw,
  Zap,
  Info,
  CheckCircle,
  ExternalLink,
  ChevronRight,
  ShieldCheck,
  Sparkles
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import {
  localizeBug,
  runRepairLoop,
  resetDirtySession,
  formatApiError
} from '../../api/client';
import StatusBadge from '../common/StatusBadge';
import ConfirmModal from '../common/ConfirmModal';

export default function RepairView({ setCurrentTab }) {
  const {
    activeSessionId,
    activeSession,
    localization,
    setLocalization,
    lastRepairResult,
    setLastRepairResult,
    refreshActiveSession
  } = useSession();

  // Localization form state
  const [issueTitle, setIssueTitle] = useState('Unhandled exception in application test suite');
  const [issueBody, setIssueBody] = useState('');
  const [stackTrace, setStackTrace] = useState('');
  const [localizing, setLocalizing] = useState(false);
  const [localizeError, setLocalizeError] = useState(null);

  // Auto-populate stack trace / stderr from active session
  useEffect(() => {
    if (activeSession?.reproduction_result?.stderr) {
      setStackTrace(activeSession.reproduction_result.stderr);
    }
  }, [activeSession]);

  // Repair Loop form state
  const [testCommand, setTestCommand] = useState('python -m unittest discover tests');
  const [failurePattern, setFailurePattern] = useState('');
  const [provider, setProvider] = useState('mock'); // 'mock' | 'ai'
  const [testTimeout, setTestTimeout] = useState(60);
  const [runningLoop, setRunningLoop] = useState(false);
  const [loopError, setLoopError] = useState(null);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [resettingDirty, setResettingDirty] = useState(false);

  useEffect(() => {
    if (activeSession?.reproduction_result?.command) {
      setTestCommand(activeSession.reproduction_result.command);
    }
    if (activeSession?.expected_failure_pattern) {
      setFailurePattern(activeSession.expected_failure_pattern);
    }
  }, [activeSession]);

  const handleLocalize = async (e) => {
    e.preventDefault();
    setLocalizing(true);
    setLocalizeError(null);
    try {
      const data = await localizeBug({
        issue_title: issueTitle,
        issue_body: issueBody || undefined,
        stack_trace: stackTrace || undefined,
        reproduction_stderr: activeSession?.reproduction_result?.stderr || undefined,
        reproduction_stdout: activeSession?.reproduction_result?.stdout || undefined,
      });
      setLocalization(data.result);
    } catch (err) {
      setLocalizeError(formatApiError(err));
    } finally {
      setLocalizing(false);
    }
  };

  const handleTriggerRepairLoop = () => {
    if (!activeSessionId) {
      setLoopError('An active session ID is required before running the repair loop.');
      return;
    }
    if (!localization || !localization.candidate_locations || localization.candidate_locations.length === 0) {
      setLoopError('Please perform bug localization first to provide candidate fix locations.');
      return;
    }
    setLoopError(null);
    setIsConfirmOpen(true);
  };

  const handleExecuteRepairLoop = async () => {
    setIsConfirmOpen(false);
    setRunningLoop(true);
    setLoopError(null);
    try {
      const result = await runRepairLoop({
        session_id: activeSessionId,
        localization,
        test_command: testCommand,
        expected_failure_pattern: failurePattern || undefined,
        provider,
        test_timeout: testTimeout,
      });
      setLastRepairResult(result);
      await refreshActiveSession(activeSessionId);
    } catch (err) {
      setLoopError(formatApiError(err));
    } finally {
      setRunningLoop(false);
    }
  };

  const handleResetDirty = async () => {
    if (!activeSessionId) return;
    setResettingDirty(true);
    try {
      await resetDirtySession({ session_id: activeSessionId });
      await refreshActiveSession(activeSessionId);
    } catch (err) {
      setLoopError(formatApiError(err));
    } finally {
      setResettingDirty(false);
    }
  };

  const isPrePatchReproduced = activeSession?.reproduction_result?.outcome === 'REPRODUCED';

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Title */}
      <div>
        <h2 className="text-xl font-bold text-slate-100 tracking-tight flex items-center gap-2">
          <Cpu className="w-5 h-5 text-cyan-400" />
          <span>Bug Repair Workspace & Bounded Autonomous Loop</span>
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Rank suspected source locations from failure evidence, configure patch synthesis parameters, and orchestrate the bounded Docker repair loop.
        </p>
      </div>

      {/* Dirty Session Alert Banner */}
      {activeSession?.is_dirty && (
        <div className="p-4 rounded-xl border border-amber-500/40 bg-amber-500/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-start gap-2.5 text-amber-300">
            <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div>
              <strong className="font-semibold block">Dirty Workspace Detected (Session: {activeSession.session_id})</strong>
              <span>
                A previous patch modified this workspace but did not achieve verified resolution. Further repair runs are blocked to protect workspace integrity.
              </span>
            </div>
          </div>
          <button
            onClick={handleResetDirty}
            disabled={resettingDirty}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold rounded-lg transition flex items-center gap-1.5 flex-shrink-0 self-end sm:self-auto shadow-md"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>{resettingDirty ? 'Resetting...' : 'Reset Dirty State'}</span>
          </button>
        </div>
      )}

      {/* Pre-patch evidence status pill */}
      <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm flex flex-wrap items-center justify-between gap-4 text-xs font-mono">
        <div className="flex items-center gap-3">
          <span className="text-slate-400">Active Session ID:</span>
          <span className="font-bold text-cyan-300">{activeSessionId || 'None'}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-400">Pre-Patch Reproduction Evidence:</span>
          {isPrePatchReproduced ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-400 font-semibold bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-0.5 rounded-full">
              <CheckCircle className="w-3.5 h-3.5" />
              CONFIRMED REPRODUCED
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-amber-400 font-semibold bg-amber-500/15 border border-amber-500/30 px-2.5 py-0.5 rounded-full">
              <AlertTriangle className="w-3.5 h-3.5" />
              MISSING PRE-PATCH REPRODUCTION
            </span>
          )}
        </div>
      </div>

      {/* Grid: Phase 4 Bug Localization */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2">
            <Search className="w-4 h-4 text-cyan-400" />
            <span>Phase 4: Deterministic Bug Localization</span>
          </h3>
          <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
            POST /localize
          </span>
        </div>

        <form onSubmit={handleLocalize} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">
                Issue Title:
              </label>
              <input
                type="text"
                required
                value={issueTitle}
                onChange={(e) => setIssueTitle(e.target.value)}
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">
                Issue Description / Context (Optional):
              </label>
              <input
                type="text"
                value={issueBody}
                onChange={(e) => setIssueBody(e.target.value)}
                placeholder="Additional issue text or bug description"
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">
              Stack Trace / Failure Traceback Evidence:
            </label>
            <textarea
              rows={4}
              value={stackTrace}
              onChange={(e) => setStackTrace(e.target.value)}
              placeholder="Paste traceback lines or let it auto-populate from reproduction runner..."
              className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl p-3 text-xs font-mono text-slate-300 focus:outline-none focus:border-cyan-500"
            />
          </div>

          <div className="flex justify-between items-center pt-2">
            <span className="text-xs text-slate-500 font-mono">
              Deterministic ranking based on stack traces and code signatures. Offline & read-only.
            </span>
            <button
              type="submit"
              disabled={localizing}
              className="px-5 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition flex items-center gap-2 shadow-glow-cyan disabled:opacity-50"
            >
              {localizing ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Localizing...</span>
                </>
              ) : (
                <span>Run Localization</span>
              )}
            </button>
          </div>

          {localizeError && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
              {localizeError}
            </div>
          )}
        </form>

        {/* Localization Results Table */}
        {localization && (
          <div className="p-5 bg-slate-950/80 border border-slate-800 rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-slate-400 uppercase font-semibold">Localization Confidence:</span>
                <span className={`text-xs font-mono font-bold px-2.5 py-0.5 rounded-full ${
                  localization.confidence === 'HIGH' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                  localization.confidence === 'MEDIUM' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30' :
                  'bg-slate-700 text-slate-300'
                }`}>
                  {localization.confidence}
                </span>
              </div>
              <span className="text-xs text-slate-500 font-mono">
                {localization.total_evidence_lines_analyzed} lines analyzed
              </span>
            </div>

            <p className="text-xs text-slate-400 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800 font-mono">
              {localization.confidence_explanation}
            </p>

            {localization.detected_exceptions?.length > 0 && (
              <div className="flex items-center gap-2 text-xs font-mono">
                <span className="text-slate-500">Detected Exceptions:</span>
                {localization.detected_exceptions.map(exc => (
                  <span key={exc} className="px-2 py-0.5 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30">
                    {exc}
                  </span>
                ))}
              </div>
            )}

            {/* Candidate Locations Table */}
            <div className="overflow-x-auto text-xs font-mono border border-slate-800 rounded-lg">
              <table className="w-full text-left border-collapse">
                <thead className="bg-slate-900/90 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-2.5 font-medium">Rank</th>
                    <th className="p-2.5 font-medium">File Path</th>
                    <th className="p-2.5 font-medium">Line</th>
                    <th className="p-2.5 font-medium">Function</th>
                    <th className="p-2.5 font-medium">Source</th>
                    <th className="p-2.5 font-medium text-right">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {localization.candidate_locations.map((loc, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/20 transition">
                      <td className="p-2.5 font-bold text-cyan-400">#{idx + 1}</td>
                      <td className="p-2.5 text-slate-200 font-semibold">{loc.file_path}</td>
                      <td className="p-2.5 text-slate-400">{loc.line_number || '—'}</td>
                      <td className="p-2.5 text-slate-400">{loc.function_name || '—'}</td>
                      <td className="p-2.5 text-slate-500">{loc.source_type}</td>
                      <td className="p-2.5 text-right font-bold text-cyan-300">
                        {(loc.relevance_score * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Phase 6B Bounded Automated Repair Loop */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-cyan-400" />
            <h3 className="text-sm font-bold text-slate-100 tracking-tight">
              Phase 6B: Bounded Automated Repair Loop Orchestration
            </h3>
          </div>
          <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
            POST /patch/repair-loop
          </span>
        </div>

        <p className="text-xs text-slate-400 leading-relaxed">
          The repair loop orchestrates patch generation, strict syntax/safety validation, in-memory patch application,
          and containerized verification. It enforces an atomic 3-attempt hard cap, a 300-second wall-clock budget, and
          automatic rollback on incomplete fixes.
        </p>

        {/* Configuration Controls */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 p-4 bg-slate-950/80 border border-slate-800 rounded-xl text-xs font-mono">
          <div>
            <label className="block text-slate-400 mb-1.5 font-medium">Provider Selection:</label>
            <div className="flex rounded-lg overflow-hidden border border-slate-700 bg-slate-900 p-0.5">
              <button
                type="button"
                onClick={() => setProvider('mock')}
                className={`flex-1 py-1.5 text-center rounded-md font-semibold transition ${
                  provider === 'mock' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Mock (Offline)
              </button>
              <button
                type="button"
                onClick={() => setProvider('ai')}
                className={`flex-1 py-1.5 text-center rounded-md font-semibold transition flex items-center justify-center gap-1 ${
                  provider === 'ai' ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Sparkles className="w-3 h-3" />
                <span>AI Provider</span>
              </button>
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">
              {provider === 'ai' ? 'Config-gated via AI_PROVIDER_API_KEY' : 'Deterministic test generator'}
            </span>
          </div>

          <div>
            <label className="block text-slate-400 mb-1.5 font-medium">Test Command (Docker):</label>
            <input
              type="text"
              required
              value={testCommand}
              onChange={(e) => setTestCommand(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-[10px] text-slate-500 mt-1 block">Allowlisted commands only</span>
          </div>

          <div>
            <label className="block text-slate-400 mb-1.5 font-medium">
              Docker Test Timeout: {testTimeout}s
            </label>
            <input
              type="range"
              min="5"
              max="300"
              step="5"
              value={testTimeout}
              onChange={(e) => setTestTimeout(e.target.value)}
              className="w-full accent-cyan-500 mt-2"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>5s</span>
              <span>Default: 60s</span>
              <span>300s</span>
            </div>
          </div>
        </div>

        {/* Action Trigger */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
          <div className="text-xs text-slate-400 font-mono">
            Requires: Active session with established <code className="text-cyan-300">REPRODUCED</code> evidence and localized candidates.
          </div>
          <button
            type="button"
            onClick={handleTriggerRepairLoop}
            disabled={runningLoop || !isPrePatchReproduced || activeSession?.is_dirty}
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 via-sky-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-bold text-xs tracking-wide shadow-glow-cyan flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            {runningLoop ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Repair Loop Running...</span>
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-current" />
                <span>Execute Bounded Repair Loop</span>
              </>
            )}
          </button>
        </div>

        {loopError && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300 font-mono">
            {loopError}
          </div>
        )}

        {/* Real Repair Loop Response Display */}
        {lastRepairResult && (
          <div className="p-6 bg-slate-950/90 border border-slate-800 rounded-xl space-y-5 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">
                  Repair Loop Execution Outcome
                </span>
                <h4 className="text-base font-bold text-slate-100 font-mono mt-0.5">
                  Session: {lastRepairResult.session_id}
                </h4>
              </div>
              <StatusBadge status={lastRepairResult.outcome} size="lg" />
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono bg-slate-900/60 p-3.5 rounded-xl border border-slate-800">
              <div>
                <span className="text-slate-500 block text-[10px]">Total Duration</span>
                <span className="font-bold text-slate-200">{lastRepairResult.total_duration_ms}ms</span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">Total Attempts</span>
                <span className="font-bold text-slate-200">{lastRepairResult.attempts?.length || 0} / 3</span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">Real AI Request</span>
                <span className={`font-bold ${lastRepairResult.real_ai_call_made ? 'text-cyan-400' : 'text-slate-400'}`}>
                  {lastRepairResult.real_ai_call_made ? 'YES (LIVE AI)' : 'NO (OFFLINE)'}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">Verification Proof</span>
                <span className="font-bold text-emerald-400">
                  {lastRepairResult.outcome === 'fix_verified' ? 'CONFIRMED' : 'NOT VERIFIED'}
                </span>
              </div>
            </div>

            {/* Details message */}
            <div className="p-3.5 bg-[#070B14] border border-slate-800/80 rounded-xl text-xs font-mono text-slate-300">
              <span className="text-slate-500 block text-[10px] uppercase mb-1">Final Details:</span>
              {lastRepairResult.final_details}
            </div>

            {/* Attempts Breakdown */}
            {lastRepairResult.attempts?.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-mono text-slate-400 font-semibold uppercase">Attempts History</span>
                <div className="divide-y divide-slate-800 border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40">
                  {lastRepairResult.attempts.map((att) => (
                    <div key={att.attempt_number} className="p-3.5 text-xs font-mono flex flex-col sm:flex-row sm:items-center justify-between gap-2 hover:bg-slate-800/20">
                      <div className="flex items-center gap-3">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-bold">
                          Attempt #{att.attempt_number}
                        </span>
                        {att.proposal_id && (
                          <span className="text-cyan-300 font-semibold">{att.proposal_id}</span>
                        )}
                        {att.verification_outcome && (
                          <StatusBadge status={att.verification_outcome} size="sm" />
                        )}
                      </div>
                      <div className="text-slate-400 text-right">
                        <span>{att.duration_ms}ms</span>
                        {att.validation_errors?.length > 0 && (
                          <span className="text-rose-400 block text-[11px]">{att.validation_errors.join('; ')}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Confirmation Modal for Potentially Destructive Repair Loop */}
      <ConfirmModal
        isOpen={isConfirmOpen}
        title="Execute Autonomous Bug Repair Loop?"
        message="This operation will propose a patch diff, validate it through PatchValidator, apply it in the isolated temporary workspace, and execute tests strictly in Docker. If verification is incomplete or regressions manifest, atomic rollback will restore the pre-repair snapshot."
        details={`Session: ${activeSessionId} | Provider: ${provider} | Command: ${testCommand}`}
        confirmText="Confirm & Run Repair Loop"
        confirmVariant="primary"
        onConfirm={handleExecuteRepairLoop}
        onCancel={() => setIsConfirmOpen(false)}
      />
    </div>
  );
}
