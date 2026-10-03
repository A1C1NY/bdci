"""Freeze episode split before exposing any development labels."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / "research/v4"
data = json.loads((base / "assets/stale/T1_T2_400_FULL.json").read_text("utf-8"))
ordered = sorted(data, key=lambda r: hashlib.sha256(("v4-stale-20260929:" + r["uid"]).encode()).hexdigest())
split = {"development": [r["uid"] for r in ordered[:80]],
         "heldout": [r["uid"] for r in ordered[80:]], "unit": "scenario", "seed": "v4-stale-20260929"}
target = base / "split.json"
if target.exists():
    assert json.loads(target.read_text("utf-8")) == split
else:
    target.write_text(json.dumps(split, indent=2), "utf-8")
r = ordered[0]
print("Split frozen: 80 development / 320 heldout scenarios")
print(json.dumps({k:v for k,v in r.items() if k not in ("haystack_session", "timestamps")}, ensure_ascii=True)[:13000])
print("sessions", len(r["haystack_session"]), "first session", str(r["haystack_session"][0])[:1800])
for i in r["relevant_session_index"]:
    print("Relevant index", i, str(r["haystack_session"][int(i)])[:4500])
