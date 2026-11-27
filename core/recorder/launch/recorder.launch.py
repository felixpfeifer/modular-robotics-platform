from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from episode_recorder_py.configuration import load_workspace_config


def _nodes(context, share: Path):
    workspace_path = Path(LaunchConfiguration("workspace_config").perform(context))
    workspace = load_workspace_config(workspace_path)
    profile = workspace["profile"]
    dataset_override = LaunchConfiguration("dataset_dir").perform(context).strip()
    dataset_dir = dataset_override or workspace["dataset_dir"]
    recorder_settings = workspace.get("recorder", {})
    source_revision = workspace.get("producer", {}).get(
        "source_revision", "development"
    )
    use_sim_time = (
        LaunchConfiguration("use_sim_time").perform(context).lower() == "true"
    )
    common = {
        "dataset_dir": str(dataset_dir),
        "recording_profiles": workspace["recording_profiles_path"],
        "task_catalog": workspace["task_catalog_path"],
    }
    nodes = []
    if workspace.get("command_bridge_enabled", True):
        nodes.append(
            Node(
                package="episode_recorder",
                executable="joint_intent_bridge.py",
                name="joint_intent_bridge",
                output="screen",
                parameters=[
                    {
                        "robot_config": profile["robot_config_path"],
                        "use_sim_time": use_sim_time,
                    }
                ],
            )
        )
    nodes.extend(
        [
            Node(
                package="episode_recorder",
                executable="validator_node.py",
                name="episode_validator",
                output="screen",
                parameters=[{**common, "use_sim_time": use_sim_time}],
            ),
            Node(
                package="episode_recorder",
                executable="recorder_node",
                name="episode_recorder",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {
                        **common,
                        "mcap_config": str(share / "config/mcap_writer_options.yaml"),
                        "recording_profile_id": workspace["recording_profile_id"],
                        "recording_profile_hash": profile["contract_hash"],
                        "task_id": workspace["task_id"],
                        "workcell_id": workspace["id"],
                        "configuration_hash": workspace["configuration_hash"],
                        "calibration_id": workspace["calibration"]["id"],
                        "calibration_hash": workspace["calibration"]["hash"],
                        "source_revision": source_revision,
                        "camera_topics": [
                            camera["topic"] for camera in profile["cameras"]
                        ],
                        "camera_expected_fps": [
                            float(camera["fps"]) for camera in profile["cameras"]
                        ],
                        "camera_fps_tolerances": [
                            float(camera.get("fps_tolerance", 0.6))
                            for camera in profile["cameras"]
                        ],
                        "joint_state_topic": profile["state"]["topic"],
                        "action_topic": profile["action"]["topic"],
                        "preflight_min_free_gib": float(
                            recorder_settings.get("preflight_min_free_gib", 10.0)
                        ),
                        "runtime_reserve_gib": float(
                            recorder_settings.get("runtime_reserve_gib", 5.0)
                        ),
                        "use_sim_time": use_sim_time,
                    }
                ],
            ),
        ]
    )
    return nodes


def generate_launch_description():
    share = Path(get_package_share_directory("episode_recorder"))
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "workspace_config",
                default_value=str(share / "config/workspaces/local_so101.yaml"),
                description="workspace-config/v1 binding robot, cameras, task, calibration and storage",
            ),
            DeclareLaunchArgument(
                "dataset_dir",
                default_value="",
                description="optional dataset directory override",
            ),
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="use the Gazebo simulation clock for acquisition timestamps",
            ),
            OpaqueFunction(function=lambda context: _nodes(context, share)),
        ]
    )
