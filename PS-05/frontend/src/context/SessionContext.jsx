import React, { createContext, useContext, useState, useEffect } from 'react';
import { fetchSession, fetchHealth } from '../api/client';

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [activeSessionId, setActiveSessionId] = useState('');
  const [activeSession, setActiveSession] = useState(null);
  const [sessionList, setSessionList] = useState([]); // User-prepared sessions during runtime
  const [localization, setLocalization] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [lastRepairResult, setLastRepairResult] = useState(null);
  const [healthStatus, setHealthStatus] = useState({ connected: false, checking: true, data: null, error: null });

  // Poll health status every 10 seconds
  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const data = await fetchHealth();
        if (mounted) {
          setHealthStatus({ connected: true, checking: false, data, error: null });
        }
      } catch (err) {
        if (mounted) {
          setHealthStatus({
            connected: false,
            checking: false,
            data: null,
            error: err.message || 'Backend unreachable',
          });
        }
      }
    };

    check();
    const interval = setInterval(check, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // Sync active session if sessionId changes
  const refreshActiveSession = async (sessionId = activeSessionId) => {
    if (!sessionId) return null;
    try {
      const data = await fetchSession(sessionId);
      setActiveSession(data);
      // Update session in list
      setSessionList(prev => {
        const idx = prev.findIndex(s => s.session_id === sessionId);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = data;
          return next;
        }
        return [data, ...prev];
      });
      return data;
    } catch (err) {
      console.warn('Could not refresh session:', sessionId, err);
      return null;
    }
  };

  const registerNewSession = (sessionData) => {
    if (!sessionData?.session_id) return;
    setActiveSessionId(sessionData.session_id);
    setActiveSession(sessionData);
    setSessionList(prev => {
      const filtered = prev.filter(s => s.session_id !== sessionData.session_id);
      return [sessionData, ...filtered];
    });
  };

  return (
    <SessionContext.Provider
      value={{
        activeSessionId,
        setActiveSessionId,
        activeSession,
        setActiveSession,
        sessionList,
        registerNewSession,
        refreshActiveSession,
        localization,
        setLocalization,
        proposal,
        setProposal,
        lastRepairResult,
        setLastRepairResult,
        healthStatus,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return ctx;
}
