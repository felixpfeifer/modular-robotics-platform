"""Bring up one SO-101 arm as a leader or follower on mock, Gazebo or real hardware."""

from pathlib import Path

import xacro
from ament_index_python.packages import get_package_share_path
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

BACKEND_TO_HARDWARE = {"mock": "mock_components", "gazebo": "gazebo", "real": "real"}
FOLLOWER_CONTROLLERS = ["joint_trajectory_controller", "gripper_controller"]
SIM_LEADER_CONTROLLERS = ["forward_position_controller"]


def controllers_for(role: str, backend: str) -> list[str]:
    if role == "follower":
        return ["joint_state_broadcaster", *FOLLOWER_CONTROLLERS]
    if backend == "real":
        return ["joint_state_broadcaster"]
    return ["joint_state_broadcaster", *SIM_LEADER_CONTROLLERS]


def launch_setup(context):
    get = lambda name: LaunchConfiguration(name).perform(context)
    role, backend, usb_port = get("role"), get("backend"), get("usb_port")
    calibration = get("calibration_file")
    namespace = get("namespace").strip("/")
    gui = get("gazebo_gui").lower() == "true"
    world = get("gazebo_world")
    headless_rendering = get("headless_rendering").lower() == "true"
    scene_camera = get("scene_camera").lower() == "true"

    if backend == "real" and not Path(usb_port).exists():
        raise RuntimeError(f"Serial port {usb_port} does not exist in this container")
    if calibration and not Path(calibration).is_file():
        raise RuntimeError(
            f"Calibration file {calibration} does not exist in this container"
        )

    use_sim_time = backend == "gazebo" or get("use_sim_time").lower() == "true"
    # A mock leader paired with a Gazebo follower consumes the follower's
    # shared clock; separately namespaced Gazebo worlds keep their own clocks.
    clock_topic = (
        f"/{namespace}/clock" if namespace and backend == "gazebo" else "/clock"
    )
    remappings = [("/clock", clock_topic)] if use_sim_time else []
    bringup = get_package_share_path("so101_bringup")
    controllers = str(bringup / "config" / "controllers.yaml")

    description = xacro.process_file(
        get_package_share_path("so_arm101_description")
        / "urdf"
        / "so_arm101.urdf.xacro",
        mappings={
            "ros2_control_file": str(bringup / "urdf" / "so101.ros2_control.xacro"),
            "ros2_control_hardware_type": BACKEND_TO_HARDWARE[backend],
            "usb_port": usb_port,
            "role": role,
            "joint_config_file": calibration,
            "simulation_controllers": controllers,
            "ros_namespace": f"/{namespace}" if namespace else "",
        },
    ).toxml()

    actions = [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            namespace=namespace,
            remappings=remappings,
            parameters=[
                {
                    "robot_description": description,
                    "use_sim_time": use_sim_time,
                    # /tf is global, so frames must be unique per arm. Joint names stay unchanged.
                    "frame_prefix": f"{namespace}/" if namespace else "",
                }
            ],
        )
    ]

    if backend == "gazebo":
        server = "" if gui else "-s "
        actions += [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    str(
                        get_package_share_path("ros_gz_sim")
                        / "launch"
                        / "gz_sim.launch.py"
                    )
                ),
                launch_arguments={
                    "gz_args": f"{server}-r -v 2 "
                    f"{'--headless-rendering ' if headless_rendering else ''}"
                    f"--physics-engine gz-physics-bullet-featherstone-plugin {world}",
                    "on_exit_shutdown": "true",
                }.items(),
            ),
            Node(
                package="ros_gz_sim",
                executable="create",
                output="screen",
                arguments=["-string", description, "-name", role],
            ),
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name=f"{role}_clock_bridge",
                arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"],
                remappings=remappings,
                output="screen",
            ),
        ]
        if scene_camera:
            actions += [
                Node(
                    package="ros_gz_bridge",
                    executable="parameter_bridge",
                    name="tabletop_camera_bridge",
                    arguments=["/top_camera/image@sensor_msgs/msg/Image[gz.msgs.Image"],
                    output="screen",
                    parameters=[{"use_sim_time": True}],
                ),
                # Object poses and cube reset for the task monitor. The world
                # name must match so101_tabletop in tabletop.sdf.
                Node(
                    package="ros_gz_bridge",
                    executable="parameter_bridge",
                    name="tabletop_task_bridge",
                    arguments=[
                        "/model/red_cube/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V",
                        "/world/so101_tabletop/set_pose@ros_gz_interfaces/srv/SetEntityPose",
                    ],
                    output="screen",
                    parameters=[{"use_sim_time": True}],
                ),
            ]
    else:
        actions.append(
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                namespace=namespace,
                parameters=[controllers, {"use_sim_time": use_sim_time}],
                remappings=[("~/robot_description", "robot_description")],
                output="screen",
                emulate_tty=True,
            )
        )

    actions += [
        Node(
            package="controller_manager",
            executable="spawner",
            namespace=namespace,
            remappings=remappings,
            parameters=[{"use_sim_time": use_sim_time}],
            # Software rendering can stall Gazebo while its first frame is
            # initialized; retain the switch request until physics advances.
            arguments=[
                controller,
                "--controller-manager-timeout",
                "60",
                "--switch-timeout",
                "60",
            ],
            output="screen",
        )
        for controller in controllers_for(role, backend)
    ]
    return actions


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "role", default_value="follower", choices=["leader", "follower"]
            ),
            DeclareLaunchArgument(
                "backend", default_value="mock", choices=["mock", "gazebo", "real"]
            ),
            DeclareLaunchArgument("namespace", default_value=""),
            DeclareLaunchArgument("usb_port", default_value="/dev/ttyACM0"),
            DeclareLaunchArgument("calibration_file", default_value=""),
            DeclareLaunchArgument("gazebo_gui", default_value="false"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("gazebo_world", default_value="empty.sdf"),
            DeclareLaunchArgument("headless_rendering", default_value="false"),
            DeclareLaunchArgument("scene_camera", default_value="false"),
            OpaqueFunction(function=launch_setup),
        ]
    )
