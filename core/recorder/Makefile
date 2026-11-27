SHELL := /bin/bash
WORKSPACE_ROOT ?= $(abspath ..)
BUILD_ROOT ?= $(CURDIR)/.build
ROS_SETUP ?= /opt/ros/jazzy/setup.bash

.PHONY: build test integration export-test upload-test verify hil

build:
	mkdir -p "$(BUILD_ROOT)/src"
	ln -sfn "$(CURDIR)" "$(BUILD_ROOT)/src/episode_recorder"
	ln -sfn "$(WORKSPACE_ROOT)/ros-interfaces/platform_common_interfaces" "$(BUILD_ROOT)/src/platform_common_interfaces"
	ln -sfn "$(WORKSPACE_ROOT)/ros-interfaces/platform_control_interfaces" "$(BUILD_ROOT)/src/platform_control_interfaces"
	ln -sfn "$(WORKSPACE_ROOT)/ros-interfaces/platform_episode_interfaces" "$(BUILD_ROOT)/src/platform_episode_interfaces"
	source "$(ROS_SETUP)" && colcon --log-base "$(BUILD_ROOT)/log" build --base-paths "$(BUILD_ROOT)/src" --build-base "$(BUILD_ROOT)/build" --install-base "$(BUILD_ROOT)/install" --event-handlers console_direct+ --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo

test: build
	source "$(ROS_SETUP)" && source "$(BUILD_ROOT)/install/setup.bash" && colcon --log-base "$(BUILD_ROOT)/test-log" test --base-paths "$(BUILD_ROOT)/src" --build-base "$(BUILD_ROOT)/build" --install-base "$(BUILD_ROOT)/install" --packages-select episode_recorder --event-handlers console_direct+ && colcon test-result --test-result-base "$(BUILD_ROOT)/build" --verbose

integration: test
	@echo "Recorder/validator integration is exercised by the synthetic MCAP pytest suite."

export-test:
	uv lock --check
	uv sync --frozen
	source "$(ROS_SETUP)" && source "$(BUILD_ROOT)/install/setup.bash" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$(CURDIR):$$PYTHONPATH" .venv/bin/python -m pytest -q test/test_lerobot_roundtrip.py test/test_upload_lerobot.py

verify: test export-test

hil:
	@test -n "$$MRP_HIL" || (echo "Set MRP_HIL=1 only on the tagged SO-101/RealSense runner" && exit 2)
	@test "$$HIL_ESTOP_CONFIRMED" = "1" || (echo "Set HIL_ESTOP_CONFIRMED=1 after the physical precheck" && exit 2)
	source "$(ROS_SETUP)" && source "$(BUILD_ROOT)/install/setup.bash" && bash scripts/run_hil.sh
