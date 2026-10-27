# PS-05: Autonomous Bug-Fixing Agent

An autonomous agent designed to detect, reproduce, localize, patch, and verify bugs in software repositories.

---

## Architecture Overview

```
PS-05/
├── backend/
│   ├── .venv/                         # Python virtual environment (gitignored)
│   ├── app/
│   │   ├── __init__.py                # App package indicator
│   │   ├── main.py                    # FastAPI application & route registration
│   │   ├── schemas.py                 # Pydantic models for request/response validation
│   │   ├── github_client.py           # GitHub REST API client with error handling
│   │   ├── issue_service.py           # URL validation and issue intake service
│   │   ├── repo_manager.py            # Workspace isolation & static test discovery
│   │   ├── sandbox_controller.py      # Docker container security control verification
│   │   ├── reproduction_runner.py     # Bug reproduction execution & outcome classification
│   │   └── sandbox_service.py         # Sandbox lifecycle coordinator
│   ├── tests/
│   │   ├── __init__.py                # Test suite package indicator
│   │   ├── test_health.py             # Phase 1: Health check automated tests
│   │   ├── test_issue_intake.py       # Phase 2: Issue intake unit & mock API tests
│   │   └── test_sandbox.py            # Phase 3: Sandbox, isolation, security & reproduction tests
│   ├── pytest.ini                     # Pytest configuration
│   └── requirements.txt               # Backend Python dependencies
├── frontend/                          # Web UI (Phase 2+)
├── docs/                              # Architecture & technical documentation
├── .gitignore                         # Ignored artifacts & secrets
└── README.md                          # Project documentation
```

---

## Prerequisites

- **Python 3.11+** (Detected: Python 3.13.15)
- **Git** (Detected: Git 2.54.0)
- **Node.js & npm** (Detected: Node v24.13.0, npm 11.6.3)
- **Docker** (Required for live containerized sandbox execution. If Docker is missing, sandbox execution is strictly blocked with `BLOCKED` status).

---

## Setup Instructions

### 1. Create and Activate Virtual Environment

Navigate to the `backend` directory and create a virtual environment at `backend/.venv`:

#### Windows (PowerShell):
```powershell
cd PS-05/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Linux / macOS (Bash / Zsh):
```bash
cd PS-05/backend
python3 -m venv .venv
source .venv/bin/activate
```

---

### 2. Install Dependencies

Install the required packages strictly into the virtual environment:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Running the Application

Start the FastAPI development server with Uvicorn:

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## API Endpoints

### 1. Health Check
- **`GET /health`**
- Returns service status and version (`HTTP 200`).

---

### 2. GitHub Issue Intake
- **`POST /issues/analyze`**
- Validates a public GitHub issue URL and returns structured issue metadata.
- Accepts strictly `https://github.com/<owner>/<repo>/issues/<number>`.

---

### 3. Repository Sandbox Preparation (Phase 3)
- **`POST /sandbox/prepare`**
- Provisions a disposable, isolated workspace in the system temporary directory outside of the application root.
- Clones the target repository and records the commit SHA.
- Statically inspects repository metadata to detect candidate test commands (without running setup scripts or arbitrary code).

#### Request:
```json
{
  "issue_url": "https://github.com/psf/requests/issues/1234",
  "commit_sha": "optional-commit-sha-to-pin"
}
```

#### Response (`HTTP 200 OK`):
```json
{
  "session_id": "a1b2c3d4",
  "repo_url": "https://github.com/psf/requests",
  "commit_sha": "abcdef1234567890abcdef1234567890abcdef12",
  "state": "ready",
  "workspace_isolated": true,
  "candidate_test_commands": ["pytest"],
  "docker_available": false,
  "security_controls_verified": false,
  "reproduction_result": null,
  "error_message": null
}
```

---

### 4. Controlled Bug Reproduction Runner (Phase 3)
- **`POST /sandbox/reproduce`**
- Executes a candidate or user-specified test command inside a verified, security-hardened container.

#### Request:
```json
{
  "session_id": "a1b2c3d4",
  "test_command": "pytest tests/test_timeout.py",
  "expected_failure_pattern": "TimeoutError"
}
```

#### Lifecycle States:
`pending` $\rightarrow$ `preparing` $\rightarrow$ `ready` $\rightarrow$ `running` $\rightarrow$ `completed` / `failed`

#### Mandatory Container Security Controls:
Before executing repository code, the following controls are strictly verified:
1. **Docker Available**: Daemon responsive.
2. **Non-Root Execution**: Container runs with `--user 1000:1000`.
3. **Dropped Capabilities**: Container runs with `--cap-drop=ALL`.
4. **No Docker Socket**: `/var/run/docker.sock` is strictly forbidden from volume mounts.
5. **No Host Credentials**: `~/.ssh`, `~/.aws`, `~/.docker` are forbidden from volume mounts.
6. **Network Disabled**: `--network=none` enforced by default.
7. **Resource Limits**: `--memory=1g`, `--cpus=1.0`, `--pids-limit=100`.
8. **Timeout Enforced**: Bounded execution time.

If any control fails or Docker is missing, execution is **stopped immediately** and marked as **`BLOCKED`**.

#### Reproduction Outcomes:
- **`REPRODUCED`**: Expected defect pattern observed with non-zero exit code.
- **`NOT_REPRODUCED`**: Command finished with exit code 0; bug did not manifest (never assumed reproduced merely because command ran).
- **`BLOCKED`**: Docker missing, security controls failed, timeout expired, or environment failure.

---

### 5. Session Status
- **`GET /sandbox/{session_id}`**
- Retrieves the current state, metadata, and reproduction outcome for a given sandbox session.

---

## Running Automated Tests

Run all unit, integration, and sandbox tests with `pytest`:

```bash
pytest -v
```

---

## Security Policy

- **No Arbitrary Code Execution on Host**: Repositories are never executed on the host system.
- **No LLM or Auto-Patching**: Phase 3 focuses solely on intake, acquisition, sandbox readiness, and bug reproduction. Fix generation and LLM calls are deferred to Phase 4.
