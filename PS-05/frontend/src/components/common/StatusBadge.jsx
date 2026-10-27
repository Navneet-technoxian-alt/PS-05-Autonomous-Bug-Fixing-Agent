import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ShieldAlert,
  Clock,
  Play,
  ShieldCheck,
  HelpCircle
} from 'lucide-react';

const BADGE_CONFIG = {
  // Reproduction outcomes
  REPRODUCED: {
    label: 'REPRODUCED',
    bg: 'bg-amber-500/15',
    text: 'text-amber-400',
    border: 'border-amber-500/40',
    icon: AlertTriangle,
    glow: 'shadow-[0_0_12px_rgba(245,158,11,0.25)]',
  },
  NOT_REPRODUCED: {
    label: 'NOT REPRODUCED',
    bg: 'bg-slate-700/30',
    text: 'text-slate-400',
    border: 'border-slate-600/40',
    icon: HelpCircle,
    glow: '',
  },
  // Verification outcomes
  fix_verified: {
    label: 'FIX VERIFIED',
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-400',
    border: 'border-emerald-500/40',
    icon: CheckCircle2,
    glow: 'shadow-[0_0_15px_rgba(16,185,129,0.3)]',
  },
  FIX_VERIFIED: {
    label: 'FIX VERIFIED',
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-400',
    border: 'border-emerald-500/40',
    icon: CheckCircle2,
    glow: 'shadow-[0_0_15px_rgba(16,185,129,0.3)]',
  },
  fix_incomplete: {
    label: 'FIX INCOMPLETE',
    bg: 'bg-amber-500/15',
    text: 'text-amber-400',
    border: 'border-amber-500/40',
    icon: AlertTriangle,
    glow: '',
  },
  FIX_INCOMPLETE: {
    label: 'FIX INCOMPLETE',
    bg: 'bg-amber-500/15',
    text: 'text-amber-400',
    border: 'border-amber-500/40',
    icon: AlertTriangle,
    glow: '',
  },
  new_regression: {
    label: 'NEW REGRESSION',
    bg: 'bg-rose-500/15',
    text: 'text-rose-400',
    border: 'border-rose-500/40',
    icon: XCircle,
    glow: 'shadow-[0_0_12px_rgba(244,63,94,0.3)]',
  },
  NEW_REGRESSION: {
    label: 'NEW REGRESSION',
    bg: 'bg-rose-500/15',
    text: 'text-rose-400',
    border: 'border-rose-500/40',
    icon: XCircle,
    glow: 'shadow-[0_0_12px_rgba(244,63,94,0.3)]',
  },
  blocked: {
    label: 'BLOCKED',
    bg: 'bg-rose-500/20',
    text: 'text-rose-400',
    border: 'border-rose-500/50',
    icon: ShieldAlert,
    glow: 'shadow-[0_0_15px_rgba(244,63,94,0.35)]',
  },
  BLOCKED: {
    label: 'BLOCKED',
    bg: 'bg-rose-500/20',
    text: 'text-rose-400',
    border: 'border-rose-500/50',
    icon: ShieldAlert,
    glow: 'shadow-[0_0_15px_rgba(244,63,94,0.35)]',
  },
  // Sandbox lifecycle states
  ready: {
    label: 'READY',
    bg: 'bg-sky-500/15',
    text: 'text-sky-400',
    border: 'border-sky-500/40',
    icon: ShieldCheck,
    glow: '',
  },
  running: {
    label: 'RUNNING',
    bg: 'bg-cyan-500/20',
    text: 'text-cyan-300',
    border: 'border-cyan-500/50',
    icon: Play,
    glow: 'animate-pulse',
  },
  completed: {
    label: 'COMPLETED',
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-400',
    border: 'border-emerald-500/40',
    icon: CheckCircle2,
    glow: '',
  },
  failed: {
    label: 'FAILED',
    bg: 'bg-rose-500/15',
    text: 'text-rose-400',
    border: 'border-rose-500/40',
    icon: XCircle,
    glow: '',
  },
  pending: {
    label: 'PENDING',
    bg: 'bg-slate-700/30',
    text: 'text-slate-400',
    border: 'border-slate-600/40',
    icon: Clock,
    glow: '',
  },
  preparing: {
    label: 'PREPARING',
    bg: 'bg-cyan-500/15',
    text: 'text-cyan-400',
    border: 'border-cyan-500/40',
    icon: Clock,
    glow: 'animate-pulse',
  },
};

export default function StatusBadge({ status, size = 'sm', showIcon = true }) {
  if (!status) return null;
  const key = String(status).trim();
  const conf = BADGE_CONFIG[key] || {
    label: key.toUpperCase(),
    bg: 'bg-slate-800',
    text: 'text-slate-300',
    border: 'border-slate-700',
    icon: HelpCircle,
    glow: '',
  };

  const IconComponent = conf.icon;
  const sizeClasses = size === 'lg'
    ? 'px-3 py-1 text-xs font-semibold'
    : 'px-2 py-0.5 text-[11px] font-medium';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border tracking-wide uppercase font-mono ${conf.bg} ${conf.text} ${conf.border} ${conf.glow} ${sizeClasses}`}
    >
      {showIcon && <IconComponent className={size === 'lg' ? 'w-3.5 h-3.5' : 'w-3 h-3'} />}
      <span>{conf.label}</span>
    </span>
  );
}
