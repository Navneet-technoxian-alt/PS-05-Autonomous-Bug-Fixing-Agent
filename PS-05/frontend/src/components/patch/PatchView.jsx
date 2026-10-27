import React, { useState } from 'react';
import {
  FileDiff,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Play,
  ShieldCheck,
  ShieldAlert,
  FileCheck,
  Send,
  Boxes,
  RotateCcw
} from 'lucide-react';
import { useSession } from '../../context/SessionContext';
import {
  proposePatch,
  validatePatch,
  applyPatch,
  verifyPatchTest,
  formatApiError
} from '../../api/client';
import DiffViewer from '../common/DiffViewer';
import StatusBadge from '../common/StatusBadge';
import ConfirmModal from '../common/ConfirmModal';

export default function PatchView() {
  const {
    activeSessionId,
    activeSession,
    localization,
    proposal,
    setProposal,
    refreshActiveSession
  } = useSession();

  // Propose states
  const [provider, setProvider] = useState('mock'); // 'mock' | 'ai'
  const [proposing, setProposing] = useState(false);
  const [proposeError, setProposeError] = useState(null);

  // Manual diff editing
  const [customDiff, setCustomDiff] = useState('');
  const activeDiff = customDiff || proposal?.unified_diff || '';

  // Validation states
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [validateError, setValidateError] = useState(null);

  // Application states
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);
  const [applyError, setApplyError] = useState(null);
  const [isApplyModalOpen, setIsApplyModalOpen] = useState(false);

  // Verification states
  const [testCommand, setTestCommand] = useState('python -m unittest discover tests');
  const [expectedPattern, setExpectedPattern] = useState('');
  const [timeout, setTimeoutVal] = useState(60);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState(null);
  const [verifyError, setVerifyError] = useState(null);

  const handlePropose = async () => {
    if (!localization) {
      setProposeError('Please run bug localization first to provide defect candidate targets.');
      return;
    }
    setProposing(true);
    setProposeError(null);
    try {
      const data = await proposePatch({
        localization,
        provider,
      });
      setProposal(data.proposal);
      setCustomDiff(data.proposal.unified_diff);
      if (data.proposal.proposed_regression_tests?.length > 0) {
        setTestCommand(data.proposal.proposed_regression_tests[0]);
      }
    } catch (err) {
      setProposeError(formatApiError(err));
    } finally {
      setProposing(false);
    }
  };

  const handleValidate = async () => {
    if (!activeSessionId) {
      setValidateError('An active session ID is required to validate patch containment.');
      return;
    }
    if (!activeDiff) {
      setValidateError('No unified diff available to validate.');
      return;
    }
    setValidating(true);
    setValidateError(null);
    setValidationResult(null);
    try {
      const data = await validatePatch({
        session_id: activeSessionId,
        unified_diff: activeDiff,
      });
      setValidationResult(data);
    } catch (err) {
      setValidateError(formatApiError(err));
    } finally {
      setValidating(false);
    }
  };

  const handleApplyClick = () => {
    if (!activeSessionId || !activeDiff) {
      setApplyError('Active session and diff are required.');
      return;
    }
    setIsApplyModalOpen(true);
  };

  const handleExecuteApply = async () => {
    setIsApplyModalOpen(false);
    setApplying(true);
    setApplyError(null);
    setApplyResult(null);
    try {
      const data = await applyPatch({
        session_id: activeSessionId,
        unified_diff: activeDiff,
      });
      setApplyResult(data);
      await refreshActiveSession(activeSessionId);
    } catch (err) {
      setApplyError(formatApiError(err));
    } finally {
      setApplying(false);
    }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    if (!activeSessionId) {
      setVerifyError('An active session ID is required.');
      return;
    }
    setVerifying(true);
    setVerifyError(null);
    setVerifyResult(null);
    try {
      const data = await verifyPatchTest({
        session_id: activeSessionId,
        test_command: testCommand || undefined,
        expected_failure_pattern: expectedPattern || undefined,
        timeout: Number(timeout),
      });
      setVerifyResult(data);
    } catch (err) {
      setVerifyError(formatApiError(err));
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Title */}
      <div>
        <h2 className="text-xl font-bold text-slate-100 tracking-tight flex items-center gap-2">
          <FileDiff className="w-5 h-5 text-cyan-400" />
          <span>Patch Synthesis, Diff Validation & Isolated Verification</span>
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Synthesize patches, inspect diffs, test filesystem containment, safely apply changes, and verify resolution in the restricted Docker sandbox.
        </p>
      </div>

      {/* Grid: Propose & Validate */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Propose Patch Card */}
        <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <span>Generate Patch Proposal</span>
            </h3>
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
              POST /patch/propose
            </span>
          </div>

          <div className="space-y-4">
            <div className="flex rounded-lg overflow-hidden border border-slate-700 bg-slate-900 p-0.5 text-xs font-mono">
              <button
                type="button"
                onClick={() => setProvider('mock')}
                className={`flex-1 py-1.5 rounded-md font-semibold transition ${
                  provider === 'mock' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Mock Deterministic Provider
              </button>
              <button
                type="button"
                onClick={() => setProvider('ai')}
                className={`flex-1 py-1.5 rounded-md font-semibold transition flex items-center justify-center gap-1 ${
                  provider === 'ai' ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Sparkles className="w-3 h-3" />
                <span>AI Model Provider</span>
              </button>
            </div>

            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-slate-500 font-mono">
                {localization ? `Using ${localization.candidate_locations?.length || 0} localized locations` : 'No localization active'}
              </span>
              <button
                onClick={handlePropose}
                disabled={proposing || !localization}
                className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs shadow-glow-cyan disabled:opacity-50 transition flex items-center gap-2"
              >
                {proposing ? 'Synthesizing...' : 'Propose Patch'}
              </button>
            </div>

            {proposeError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                {proposeError}
              </div>
            )}

            {proposal && (
              <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-2 text-xs font-mono">
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Proposal ID:</span>
                  <span className="text-cyan-300 font-semibold">{proposal.proposal_id}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Provider:</span>
                  <span className="text-slate-300 uppercase">{proposal.provider_name}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Rationale:</span>
                  <p className="text-slate-300 text-[11px] mt-0.5">{proposal.rationale}</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Validate Diff Card */}
        <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2">
              <FileCheck className="w-4 h-4 text-cyan-400" />
              <span>Validate Diff Against Workspace</span>
            </h3>
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
              POST /patch/validate
            </span>
          </div>

          <p className="text-xs text-slate-400">
            Strict read-only safety check: verifies that the diff is syntactically valid, matches target file hunks, and does not touch protected or sensitive files.
          </p>

          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-slate-500 font-mono">
              Session: <strong className="text-cyan-300">{activeSessionId || 'None'}</strong>
            </span>
            <button
              onClick={handleValidate}
              disabled={validating || !activeDiff || !activeSessionId}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold text-xs disabled:opacity-50 transition"
            >
              {validating ? 'Validating...' : 'Validate Diff'}
            </button>
          </div>

          {validateError && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
              {validateError}
            </div>
          )}

          {validationResult && (
            <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-2 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Validation Status:</span>
                <span className={`font-bold ${validationResult.is_valid ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {validationResult.is_valid ? 'VALID & SAFE' : 'INVALID'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Hunks Analyzed:</span>
                <span className="text-slate-300">{validationResult.total_hunks_analyzed}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Affected Files:</span>
                <span className="text-cyan-300">{validationResult.affected_files?.join(', ') || 'None'}</span>
              </div>
              {validationResult.errors?.length > 0 && (
                <div className="p-2 bg-rose-500/10 border border-rose-500/30 rounded text-rose-300 text-[11px]">
                  {validationResult.errors.join('; ')}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Unified Diff Viewer & Safe Apply Section */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileDiff className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-bold text-slate-100 tracking-tight">
              Review Unified Diff Content
            </h3>
          </div>
          <button
            type="button"
            onClick={handleApplyClick}
            disabled={applying || !activeDiff || !activeSessionId}
            className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-xs shadow-glow-emerald disabled:opacity-40 transition flex items-center gap-2"
          >
            {applying ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Applying...</span>
              </>
            ) : (
              <>
                <Send className="w-3.5 h-3.5" />
                <span>Apply Patch to Workspace</span>
              </>
            )}
          </button>
        </div>

        {applyError && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
            {applyError}
          </div>
        )}

        {applyResult && (
          <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-2 text-xs font-mono">
            <div className="flex justify-between items-center">
              <span className="text-slate-500">Application Status:</span>
              <span className={`font-bold ${applyResult.applied ? 'text-emerald-400' : 'text-rose-400'}`}>
                {applyResult.applied ? 'APPLIED SUCCESSFULLY' : 'APPLICATION FAILED'}
              </span>
            </div>
            {applyResult.applied_files?.length > 0 && (
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Applied Files:</span>
                <span className="text-cyan-300">{applyResult.applied_files.join(', ')}</span>
              </div>
            )}
            {applyResult.errors?.length > 0 && (
              <div className="p-2 bg-rose-500/10 border border-rose-500/30 rounded text-rose-300 text-[11px]">
                {applyResult.errors.join('; ')}
              </div>
            )}
          </div>
        )}

        {/* Diff Viewer Component */}
        <DiffViewer unifiedDiff={activeDiff} filename="candidate_patch.diff" />
      </div>

      {/* Phase 5B Isolated Docker Verification */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-bold text-slate-100 tracking-tight">
              Phase 5B: Isolated Post-Patch Docker Test Verification
            </h3>
          </div>
          <span className="text-[10px] font-mono uppercase bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
            POST /patch/verify-test
          </span>
        </div>

        <p className="text-xs text-slate-400">
          Executes test runner inside a restricted, non-networked Docker container.
          <strong className="text-emerald-400 font-medium"> FIX_VERIFIED</strong> is returned strictly when prior reproduction evidence is on record and the failure pattern is resolved.
        </p>

        <form onSubmit={handleVerify} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">Test Command:</label>
              <input
                type="text"
                required
                value={testCommand}
                onChange={(e) => setTestCommand(e.target.value)}
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">Expected Failure Pattern:</label>
              <input
                type="text"
                value={expectedPattern}
                onChange={(e) => setExpectedPattern(e.target.value)}
                placeholder="Pattern that must be absent"
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5 font-medium">Timeout (seconds):</label>
              <input
                type="number"
                min="5"
                max="300"
                value={timeout}
                onChange={(e) => setTimeoutVal(e.target.value)}
                className="w-full bg-slate-950/80 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          <div className="flex justify-end pt-1">
            <button
              type="submit"
              disabled={verifying || !activeSessionId}
              className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-semibold text-xs tracking-wide shadow-glow-cyan flex items-center gap-2 disabled:opacity-40 transition"
            >
              {verifying ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Verifying in Container...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Run Verification</span>
                </>
              )}
            </button>
          </div>

          {verifyError && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
              {verifyError}
            </div>
          )}

          {verifyResult && (
            <div className="p-5 bg-slate-950/90 border border-slate-800 rounded-xl space-y-4 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 uppercase font-semibold">Verification Outcome</span>
                <StatusBadge status={verifyResult.outcome} size="lg" />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                <div>
                  <span className="text-slate-500 text-[10px] block">Exit Code</span>
                  <span className="font-bold text-slate-200">{verifyResult.exit_code ?? 'None'}</span>
                </div>
                <div>
                  <span className="text-slate-500 text-[10px] block">Duration</span>
                  <span className="font-bold text-slate-200">{verifyResult.duration_ms}ms</span>
                </div>
                <div>
                  <span className="text-slate-500 text-[10px] block">Pre-Patch Observed</span>
                  <span className={verifyResult.pre_patch_observed ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                    {verifyResult.pre_patch_observed ? 'YES' : 'NO'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 text-[10px] block">Timed Out</span>
                  <span className={verifyResult.timed_out ? 'text-rose-400 font-bold' : 'text-slate-300'}>
                    {verifyResult.timed_out ? 'YES' : 'NO'}
                  </span>
                </div>
              </div>

              <div className="p-3 bg-[#070B14] border border-slate-800 rounded-lg text-slate-300 text-[11px]">
                <span className="text-slate-500 block text-[10px] uppercase mb-0.5">Details:</span>
                {verifyResult.details}
              </div>

              {verifyResult.stderr && (
                <div>
                  <span className="text-slate-500 text-[10px] block mb-1">Standard Error:</span>
                  <pre className="p-3 bg-[#070B14] border border-slate-800 rounded-lg text-rose-300 text-[11px] overflow-x-auto max-h-40 leading-relaxed">
                    {verifyResult.stderr}
                  </pre>
                </div>
              )}
            </div>
          )}
        </form>
      </div>

      {/* Confirmation Modal for Applying Patch */}
      <ConfirmModal
        isOpen={isApplyModalOpen}
        title="Apply Patch to Temporary Workspace?"
        message="This action will write modified file hunks into the session's isolated temporary directory. If verification fails, you will need to reset or roll back the workspace to prevent dirty state."
        details={`Session: ${activeSessionId} | Target Diff Size: ${activeDiff.length} chars`}
        confirmText="Confirm & Apply"
        confirmVariant="warning"
        onConfirm={handleExecuteApply}
        onCancel={() => setIsApplyModalOpen(false)}
      />
    </div>
  );
}
