import os
import sys

# Make `import worker` resolve to orchestration/worker.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
