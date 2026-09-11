# MedFlow

A local desktop patient-management application built with Python, CustomTkinter, and SQLite.

## Features

- Native desktop GUI
- Modern CustomTkinter interface
- Light/dark/system appearance
- Patient directory
- Search by patient name or ID
- Patient profile display
- Add patient workflow
- Large text areas for medical history and diagnosis
- Delete patient with confirmation
- Persistent local SQLite database
- Automatic patient ID generation without reusing deleted IDs
- No API keys
- No `.env`
- No internet connection required for normal operation

## Run locally

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it.

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python main.py
```

The SQLite database `medflow.db` is created automatically beside the application.

## Package for Windows

Install PyInstaller:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller --onefile --windowed --name MedFlow main.py
```

The executable will appear in:

```text
dist/MedFlow.exe
```

## Development vs release

During development, run:

```bash
python main.py
```

After making changes, restart the application to see them.

Only build the `.exe` when you are ready to distribute a release.

## Future architecture

The application is deliberately separated into:

```text
GUI
 ↓
Application logic
 ↓
Database layer
 ↓
SQLite
```

This makes it possible to replace SQLite later with PostgreSQL or another remote database without rebuilding the entire user interface.
