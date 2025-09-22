#!/usr/bin/env python3
"""
Simple wrapper for duo_student_cleanup.py that uses .env file by default
"""

import subprocess
import sys
from pathlib import Path

# Add the project root to path to find the .env file
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Run the main script - it will automatically load from .env
subprocess.run([
    sys.executable,
    str(Path(__file__).parent / "duo_student_cleanup.py"),
    *sys.argv[1:]  # Pass any additional arguments
])