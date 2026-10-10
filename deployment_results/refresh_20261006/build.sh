#!/usr/bin/env bash
set -eo pipefail
root="$HOME/liftrace_board_trials_20260928"
source /opt/ros/noetic/setup.bash
cd "$root/vision_ws"
catkin_make -DPYTHON_EXECUTABLE=/usr/bin/python3 -DCATKIN_WHITELIST_PACKAGES= -j2 -l2
source "$root/vision_ws/devel/setup.bash"
cd "$root/patrol_uav_ws-patrol_planner"
catkin_make -DROS_EDITION=ROS1 -DPYTHON_EXECUTABLE=/usr/bin/python3 -DCATKIN_WHITELIST_PACKAGES= -DFAST_LIO_MATCH_THREADS=3 -j2 -l2
