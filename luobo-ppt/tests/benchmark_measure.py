"""Print raw scaling observations; deliberately contains no timing assertions."""
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_source import measure

rows = []
for count in (16000, 64000):
    text = "\n".join(f"Revenue {n}M" for n in range(count))
    durations = []
    for _ in range(3):
        start = time.perf_counter()
        result = measure(text)
        durations.append(time.perf_counter() - start)
    rows.append({"records": count, "characters": len(text), "seconds": durations,
                 "result_count": len(result["data_points"]), "data_points": result["data_points"]})
print(json.dumps({"python": sys.version, "platform": platform.platform(), "measurements": rows}, indent=2))
