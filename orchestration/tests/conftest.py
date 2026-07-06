import os
import sys

# Make `import ornith_worker` resolve to orchestration/ornith_worker.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
