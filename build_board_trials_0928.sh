#!/usr/bin/env bash
set -e
cd /home/orangepi/liftrace_board_trials_20260928
mkdir -p deployment_results
OPENCV_CMAKE_DIR=/usr/lib/aarch64-linux-gnu/cmake/opencv4 BUILD_JOBS=2 bash top_level_scripts/build_competition.sh > deployment_results/build.log 2>&1
