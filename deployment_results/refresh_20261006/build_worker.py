import subprocess,json,time
from pathlib import Path
r=Path(__file__).parent
with (r/"build.log").open("w") as f:
 p=subprocess.run(["bash",str(r/"build.sh")],stdout=f,stderr=subprocess.STDOUT)
(r/"build_result.json").write_text(json.dumps({"returncode":p.returncode,"finished":time.time()}))
