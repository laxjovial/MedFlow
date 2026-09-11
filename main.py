"""MedFlow launcher.

The application itself lives in the ``app`` package. This file exists so that
``python main.py`` keeps working exactly as it did before the refactor — the
command people already have in their notes, their shell history and their IDE run
configurations does not have to change because the code behind it was reorganised.
"""

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
