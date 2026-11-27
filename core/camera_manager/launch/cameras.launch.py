from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="camera_manager",
                executable="camera_manager_node",
                name="camera_manager",
                output="screen",
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("camera_manager"), "config", "cameras.yaml"]
                    )
                ],
            ),
        ]
    )
