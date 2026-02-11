# qlink-irc
IRC Project


## Prerequisites

- Python **3.8+**
- pip (comes with Python)

Verify installation:

```bash
python --version
pip --version
````

---

## Setup Instructions

### 1. Clone the Repository

```bash
[git clone <your-repo-url>](https://github.com/Qlink149/qlink-irc.git)
cd qlink-irc
```

---

### 2. Create Virtual Environment

#### Windows

```bash
python -m venv venv
```

#### macOS / Linux

```bash
python3 -m venv venv
```

---

### 3. Activate Virtual Environment

#### Windows (PowerShell / CMD)

```bash
venv\Scripts\activate
```

#### macOS / Linux

```bash
source venv/bin/activate
```

You should see `(venv)` in your terminal once activated.

---

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 5. Run the Project

```bash
python main_2.py
```

---

## Web App (Frontend + Backend)

### Backend (API)

Install deps:

```bash
pip install -r requirements.txt
```

Run the API:

```bash
python api_server.py
```

The API runs on `http://127.0.0.1:8000` and exposes:

- `POST /api/reconcile` (multipart form-data) → returns the generated CSV download
- `GET /api/health`
- `GET /api/history` → lists stored files grouped by month
- `GET /api/download/{month}/{filename}` → secure file download

### Frontend (Vite)

Create `Qlink/.env.local` (or copy from `Qlink/.env.example`) with:

```bash
VITE_API_BASE=http://127.0.0.1:8000
```

```bash
cd Qlink
npm install
npm run dev
```

Open the URL shown by Vite (usually `http://localhost:5173`), upload the files, then click **Run reconciliation**.

---

## Deactivate Virtual Environment

```bash
deactivate
```
