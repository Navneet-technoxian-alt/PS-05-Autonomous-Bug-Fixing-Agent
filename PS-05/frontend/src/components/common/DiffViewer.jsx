import React, { useState } from 'react';
import { Copy, Check, FileCode, ArrowDownRight } from 'lucide-react';

export default function DiffViewer({ unifiedDiff, filename, maxLines = 500 }) {
  const [copied, setCopied] = useState(false);

  if (!unifiedDiff || !unifiedDiff.trim()) {
    return (
      <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl bg-slate-950/40 text-slate-500 font-mono text-sm">
        <FileCode className="w-8 h-8 mx-auto mb-2 opacity-40 text-cyan-400" />
        No unified diff content to display.
      </div>
    );
  }

  const lines = unifiedDiff.split('\n');
  const displayLines = lines.slice(0, maxLines);

  const handleCopy = () => {
    navigator.clipboard.writeText(unifiedDiff);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border border-slate-800 rounded-xl bg-[#090D1A] overflow-hidden shadow-xl">
      {/* Diff Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/80 border-b border-slate-800 text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-300">
          <FileCode className="w-4 h-4 text-cyan-400" />
          <span className="font-semibold text-cyan-300">{filename || 'unified.diff'}</span>
          <span className="text-slate-500">({lines.length} lines)</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-md transition text-[11px]"
          title="Copy diff to clipboard"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy Diff</span>
            </>
          )}
        </button>
      </div>

      {/* Diff Lines Container */}
      <div className="overflow-x-auto text-[12px] font-mono leading-relaxed max-h-[480px] p-2">
        <table className="w-full border-collapse">
          <tbody>
            {displayLines.map((line, idx) => {
              const isAdd = line.startsWith('+') && !line.startsWith('+++');
              const isDel = line.startsWith('-') && !line.startsWith('---');
              const isHunk = line.startsWith('@@');
              const isHeader = line.startsWith('---') || line.startsWith('+++');

              let rowClass = 'text-slate-400 hover:bg-slate-800/30';
              let linePrefix = ' ';
              if (isAdd) {
                rowClass = 'diff-line-add hover:bg-emerald-500/20';
                linePrefix = '+';
              } else if (isDel) {
                rowClass = 'diff-line-del hover:bg-rose-500/20';
                linePrefix = '-';
              } else if (isHunk) {
                rowClass = 'diff-line-hunk font-semibold';
              } else if (isHeader) {
                rowClass = 'text-cyan-400/80 font-semibold bg-cyan-950/20';
              }

              return (
                <tr key={idx} className={`${rowClass} transition-colors select-text`}>
                  <td className="w-10 text-right pr-3 pl-2 py-0.5 text-slate-600 select-none text-[11px] border-r border-slate-800/60 font-mono">
                    {idx + 1}
                  </td>
                  <td className="px-3 py-0.5 whitespace-pre">
                    {line}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {lines.length > maxLines && (
        <div className="px-4 py-2 text-center text-xs text-slate-500 bg-slate-900/60 border-t border-slate-800">
          Truncated display to first {maxLines} of {lines.length} lines.
        </div>
      )}
    </div>
  );
}
