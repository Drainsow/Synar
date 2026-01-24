# Synar

Synar is a Discord bot written in Python using `discord.py`.

This repository contains the full source code.

---

## Requirements

- Python **3.10+**
- Git
- Discord bot token

---

## Project Structure

Synar/
├─ src/
│ └─ main.py # Application entry point
├─ requirements.txt # Python dependencies
├─ .gitignore
├─ .env.example # Environment variable template
└─ README.md

---

## Setup (Local Development)

### 1. Clone the repository

```bash
git clone <REPO_URL>
cd Synar
```

---

### 2. Create a virtual environment

A virtual environment is required to keep project dependencies isolated.

#### Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` in your shell prompt once it is active.

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Create the `.env` file

Copy the environment template:

```bash
cp .env.example .env
```

Then edit `.env` and fill in the required values.

Example:

```env
ENV=dev
LOG_LEVEL=DEBUG
DISCORD_TOKEN=your_discord_bot_token_here
```

---

### 5. Run the project

```bash
python src/main.py
```

---

## Environment Variables

### `ENV`

Controls the runtime mode.

- `dev` – development mode (local testing, verbose logging)
- `prod` – production mode (clean logging, live deployment)

---

### `LOG_LEVEL`

Controls logging verbosity.

Valid values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Recommended values:

- `DEBUG` for development
- `INFO` for production

---

### `DISCORD_TOKEN`

The Discord bot token from the Discord Developer Portal.

---

## Notes

- Always run the project inside the virtual environment.
- If dependencies break, you can safely delete `.venv/` and recreate it.
- The same setup works on Windows, Linux, and Raspberry Pi.

---

## License

TBD
