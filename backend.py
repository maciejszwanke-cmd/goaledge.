
from __future__ import annotations
import os
import sys

# Add parent directory to import path so Render can find goaledge_integrated_v1
parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)

from goaledge_api import HOST, PORT, main

if __name__ == "__main__":
    main()
