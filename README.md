# BVC Financial — Full Stack (Frontend + Backend)

A full-stack **BVC Financial** project containing:

- **Backend (Python):** API + database access + scraping/validation utilities  
- **Frontend (JavaScript):** dashboard UI (Vite-based)

> Repository: `elbotiimrane/bvc-financial-frontend-backend`

---

## Project structure

```text
bvc-financial-frontend-backend/
  BVC_Financial_Backend/
  BVC_Financial_Frontend/
```

### Backend (`BVC_Financial_Backend/`)
Key files you’ll find:
- `main.py` — API server entry point
- `db.py` — database layer
- `scraper/` — ingestion/scraping module
- `verify_data.py` — data validation helpers
- `check_outliers.py` — outlier checks
- `listings.db` — local SQLite database (dev)

### Frontend (`BVC_Financial_Frontend/`)
Key files you’ll find:
- `index.html` — app entry HTML
- `src/` — frontend source code
- `public/` — static assets
- `vite.config.js` — Vite config
- `package.json` — frontend dependencies + scripts

---

## Prerequisites

- **Python 3.10+** (recommended)
- **Node.js 18+** (recommended)
- **Git**

---

## Run locally (recommended order)

### 1) Clone the repository
```bash
git clone https://github.com/elbotiimrane/bvc-financial-frontend-backend.git
cd bvc-financial-frontend-backend
```

---

## Backend setup & run (Python)

### 2) Go to backend folder
```bash
cd BVC_Financial_Backend
```

### 3) Create & activate a virtual environment
**Windows**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4) Install backend dependencies
```bash
pip install -r requirements.txt
```

### 5) Start the backend
Depending on how `main.py` is implemented:

**Option A (direct)**
```bash
python main.py
```

**Option B (FastAPI style)**
```bash
uvicorn main:app --reload
```

Backend will typically run on something like:
- `http://localhost:8000`

> Note: This repo includes a local SQLite database file: `listings.db`.

---

## Frontend setup & run (Vite)

### 6) Open a second terminal and go to frontend folder
From the repo root:
```bash
cd BVC_Financial_Frontend
```

### 7) Install frontend dependencies
```bash
npm install
```

### 8) Start the frontend dev server
```bash
npm run dev
```

Frontend will typically run on something like:
- `http://localhost:5173`

---

## Configure the API URL (frontend → backend)

If the frontend needs an API base URL, common patterns are:

- Create a `.env` file inside `BVC_Financial_Frontend/`:
  ```bash
  VITE_API_URL=http://localhost:8000
  ```
- Or update a config constant inside `src/`

Check `BVC_Financial_Frontend/src/` to see how requests are made (fetch/axios) and what variable name is used.

---

## Common tasks

### Validate data (backend)
From `BVC_Financial_Backend/`:
```bash
python verify_data.py
```

### Check outliers (backend)
From `BVC_Financial_Backend/`:
```bash
python check_outliers.py
```

---

## Notes / status

- The backend currently includes a local database (`listings.db`) which is convenient for demos but may be replaced by a managed DB later.
- If you publish/deploy this project, consider:
  - Moving configuration to environment variables (`.env`)
  - Adding `.gitignore` rules for logs/db files (if needed)
  - Adding tests and CI
