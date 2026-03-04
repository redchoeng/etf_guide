#!/usr/bin/env python
"""Quick launcher for the ETF Grid Buying Guide dashboard."""

import subprocess
import sys
from pathlib import Path


def main():
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.headless", "true",
    ])


if __name__ == "__main__":
    main()
