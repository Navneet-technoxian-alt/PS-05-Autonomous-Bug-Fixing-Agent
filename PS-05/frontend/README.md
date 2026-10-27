# PS-05 Frontend Dashboard

A modern, cybersecurity / SOC-inspired real-time web dashboard for the **PS-05 Autonomous Bug-Fixing Agent**.

---

## Features

- **SOC Command Center Aesthetics**: Dark navy theme (`#070B14`), glowing cyan/blue accents, accessible contrast, and responsive layout.
- **Real-Time Backend Health**: Top bar live health check polling `/health` with roundtrip latency indicator.
- **Phase 2 & 3: Issue Intake & Sandbox**: GitHub issue URL intake, commit pinning, isolated workspace provisioning, and Docker bug reproduction runner.
- **Phase 4: Bug Localization**: Deterministic stack trace & failure evidence localization ranking candidate fix files and lines.
- **Phase 6B: Bounded Automated Repair Loop**: Orchestrates patch synthesis, syntax validation, in-memory patch application, and isolated Docker verification with a 3-attempt hard cap and 300s budget.
- **Phase 5A & 5B: Patch Review & Verification**: Syntax-highlighted unified diff viewer, containment validator, safe patch applier with confirmation modal, and isolated container test verification.
- **Security First**: Zero client-side tokens, strict non-root Docker execution (`--network=none`, `--cap-drop=ALL`), and explicit user confirmations for destructive operations.

---

## Tech Stack

- **React 18**
- **Vite 6**
- **Tailwind CSS 3**
- **Axios**
- **Lucide React** (Security & SOC icon set)

---

## Getting Started

### 1. Prerequisites

- **Node.js**: v18+ (tested on Node v24)
- **FastAPI Backend Running**: Ensure the PS-05 backend server is active on `http://127.0.0.1:8000`:
  ```powershell
  cd PS-05/backend
  .\.venv\Scripts\Activate.ps1
  python -m uvicorn app.main:app --reload
  ```

### 2. Install Dependencies

From `PS-05/frontend`:
```bash
npm install
```

### 3. Environment Configuration

Create or modify `.env` (optional; defaults to `http://127.0.0.1:8000`):
```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 4. Run Development Server

```bash
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

### 5. Production Build

To validate and compile the optimized production bundle:
```bash
npm run build
```
Preview the built bundle:
```bash
npm run preview
```
