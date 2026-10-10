#!/usr/bin/env bash
set -eo pipefail
root="$HOME/liftrace_board_trials_20260928"
source "$root/deployment/site_20260928/environment.sh"
cd "$root/patrol_uav_ws-patrol_planner"
catkin_make -DROS_EDITION=ROS1 -DPYTHON_EXECUTABLE=/usr/bin/python3 -DCATKIN_WHITELIST_PACKAGES= -DFAST_LIO_MATCH_THREADS=3 -j2 -l2
catkin_make -DFAST_LIO_MATCH_THREADS=3 matching_buffers_test -j2 -l2
source "$root/patrol_uav_ws-patrol_planner/devel/setup.bash"
"$root/patrol_uav_ws-patrol_planner/devel/lib/fast_lio/matching_buffers_test" > "$root/deployment_results/refresh_20261006/matching_test.log" 2>&1
