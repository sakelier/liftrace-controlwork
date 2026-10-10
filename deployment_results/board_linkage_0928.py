
import pathlib,subprocess,json,os
root=pathlib.Path('/home/orangepi/liftrace_board_trials_20260928');out=root/'deployment_results'
libs=[]
paths=['patrol_uav_ws-patrol_planner/devel/lib/plan_manage/fast_planner_node',
       'patrol_uav_ws-patrol_planner/devel/lib/plan_manage/traj_server',
       'patrol_uav_ws-patrol_planner/devel/lib/patrol_control/patrol_control',
       'patrol_uav_ws-patrol_planner/devel/lib/fast_lio/fastlio_mapping',
       'patrol_uav_ws-patrol_planner/devel/lib/freedom/freedom_node',
       'vision_ws/devel/lib/uav_vision/circle_detector_node']
for rel in paths:
    p=root/rel;assert p.exists(),str(p)
    r=subprocess.run(['ldd',str(p)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    assert r.returncode==0 and 'not found' not in r.stdout,r.stdout
    libs.append(dict(binary=rel,status='PASS',opencv=[v.strip() for v in r.stdout.splitlines() if 'opencv' in v]))
import cv2,numpy as np
from cv_bridge import CvBridge
img=np.zeros((24,32,3),np.uint8);msg=CvBridge().cv2_to_imgmsg(img,encoding='bgr8')
assert CvBridge().imgmsg_to_cv2(msg,'bgr8').shape==img.shape
import roslib.packages
for pkg,exe in [('uav_board_trials','trial_manager.py'),('uav_board_trials','trial_recorder.py'),('uav_mission','navigation_planner_bridge.py'),('camera_sdk','camera_sdk.py'),('uav_vision','target_detector_rknn.py')]:
    located=roslib.packages.find_node(pkg,exe)
    assert located,(pkg,exe)
    libs.append(dict(package=pkg,executable=exe,status='PASS',path=located))
(out/'linkage_validation.json').write_text(json.dumps(libs,indent=2))
print(json.dumps(libs,indent=2))
