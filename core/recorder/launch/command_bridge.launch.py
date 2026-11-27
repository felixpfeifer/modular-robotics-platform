"""Standalone follower command bridge, independent of the recording session.

Run it with the cell and set ``command_bridge_enabled: false`` in the workspace
config so the recorder launch does not start a second consumer.
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from episode_recorder_py.configuration import load_workspace_config


def _nodes(context):
    workspace = load_workspace_config(
        Path(LaunchConfiguration("workspace_config").perform(context))
    )
    use_sim_time = (
        LaunchConfiguration("use_sim_time").perform(context).lower() == "true"
    )
    return [
        Node(
            package="episode_recorder",
            executable="joint_intent_bridge.py",
            name="joint_intent_bridge",
            output="screen",
            parameters=[
                {
                    "robot_config": workspace["profile"]["robot_config_path"],
                    "use_sim_time": use_sim_time,
                    # Simulated nodes can see adjacent /clock ticks; hardware keeps zero.
                    "future_tolerance_ms": 10 if use_sim_time else 0,
                }
            ],
        )
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "workspace_config", description="workspace-config/v1 file"
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            OpaqueFunction(function=_nodes),
        ]
    )
