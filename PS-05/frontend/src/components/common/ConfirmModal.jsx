import React from 'react';
import { AlertTriangle, ShieldCheck, X } from 'lucide-react';

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = 'Proceed',
  cancelText = 'Cancel',
  confirmVariant = 'danger', // 'danger' | 'warning' | 'primary'
  onConfirm,
  onCancel,
  isProcessing = false,
  details = null,
}) {
  if (!isOpen) return null;

  const variantStyles = {
    danger: {
      btn: 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-900/30',
      icon: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    },
    warning: {
      btn: 'bg-amber-600 hover:bg-amber-500 text-white shadow-amber-900/30',
      icon: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
    },
    primary: {
      btn: 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-cyan-900/30',
      icon: 'text-cyan-400 bg-cyan-500/15 border-cyan-500/30',
    },
  }[confirmVariant] || variantStyles.primary;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-md border border-slate-700/80 bg-slate-900/95 rounded-2xl shadow-2xl overflow-hidden p-6 relative animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
      >
        <button
          onClick={onCancel}
          disabled={isProcessing}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-start gap-4">
          <div className={`p-3 rounded-xl border ${variantStyles.icon} flex-shrink-0`}>
            <AlertTriangle className="w-6 h-6" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
            <p className="mt-2 text-sm text-slate-300 leading-relaxed">{message}</p>
            {details && (
              <div className="mt-3 p-3 bg-slate-950/70 border border-slate-800 rounded-lg text-xs font-mono text-slate-400 max-h-36 overflow-y-auto">
                {details}
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3 pt-4 border-t border-slate-800/80">
          <button
            type="button"
            onClick={onCancel}
            disabled={isProcessing}
            className="px-4 py-2 text-sm font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700 rounded-lg transition"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isProcessing}
            className={`px-4 py-2 text-sm font-semibold rounded-lg shadow-lg transition flex items-center gap-2 ${variantStyles.btn} ${
              isProcessing ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {isProcessing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Processing...</span>
              </>
            ) : (
              confirmText
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
