#!/usr/bin/env python3
"""
Citation Impact Analyzer - Terminal UI Launcher

Simply run this file to start the interactive citation analysis tool.

Usage:
    python run.py

or make it executable:
    chmod +x run.py
    ./run.py
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from citationimpact.ui.terminal_ui import main
    main()
except ImportError as e:
    print("\n" + "="*70)
    print("ERROR: Required dependencies not installed!")
    print("="*70)
    print(f"\nDetails: {e}")
    print("\nPlease install dependencies first:")
    print("\n  pip install -r requirements.txt")
    print("\n" + "="*70 + "\n")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n\nExiting... Goodbye! 👋\n")
    sys.exit(0)
except Exception as e:
    print("\n" + "="*70)
    print("UNEXPECTED ERROR!")
    print("="*70)
    print(f"\n{type(e).__name__}: {e}")
    print("\nPlease report this issue if it persists.")
    print("="*70 + "\n")
    sys.exit(1)
