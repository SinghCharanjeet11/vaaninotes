"""VaaniNotes: an offline, multilingual lecture & meeting assistant for Snapdragon PCs."""

import os
from pathlib import Path

__version__ = "1.0.0"

# Keep downloaded tokenizer/model files inside the project so the app is portable
# and runs fully offline once set up.
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent.parent / ".cache" / "hf"))
