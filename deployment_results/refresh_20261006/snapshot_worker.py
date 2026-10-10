import subprocess,json,time
from pathlib import Path
r=Path(__file__).parent
with (r/"snapshot_build.log").open("w") as f:
 p=subprocess.run(["bash",str(r/"build_snapshot.sh")],stdout=f,stderr=subprocess.STDOUT)
(r/"snapshot_result.json").write_text(json.dumps({"returncode":p.returncode,"finished":time.time()}))
