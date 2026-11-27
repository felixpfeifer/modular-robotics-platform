# flake8: noqa: Q000
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def validate_policy_stage(context, *args, **kwargs):
    if LaunchConfiguration("use_policy").perform(context).lower() == "true":
        raise RuntimeError(
            "policy_client is Stage 2 and is not included in this Stage 1 package"
        )
    return []


def overrides(context, names):
    """Launch arguments that were given explicitly; empty ones leave the parameter file's value."""
    result = {"use_sim_time": LaunchConfiguration("use_sim_time")}
    for name, parameter in names.items():
        value = LaunchConfiguration(name).perform(context)
        if value:
            result[parameter] = int(value)
    return result


def nodes(context, *args, **kwargs):
    share = FindPackageShare("control_arbiter").perform(context)
    arbiter_config = (
        LaunchConfiguration("arbiter_config").perform(context)
        or f"{share}/config/arbiter.yaml"
    )
    teleop_config = (
        LaunchConfiguration("teleop_config").perform(context)
        or f"{share}/config/teleop.yaml"
    )
    return [
        Node(
            package="control_arbiter",
            executable="arbiter",
            name="control_arbiter",
            output="screen",
            parameters=[
                arbiter_config,
                {
                    "active_source": LaunchConfiguration("mode"),
                    **overrides(context, {"source_timeout_ms": "source_timeout_ms"}),
                },
            ],
        ),
        Node(
            package="control_arbiter",
            executable="teleop_source",
            name="teleop_source",
            output="screen",
            parameters=[
                teleop_config,
                overrides(context, {"intent_validity_ms": "validity_ms"}),
            ],
            condition=IfCondition(LaunchConfiguration("use_teleop")),
        ),
    ]


def generate_launch_description():
    mode = LaunchConfiguration("mode")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "mode", default_value="none", choices=["teleop", "policy", "none"]
            ),
            DeclareLaunchArgument("use_teleop", default_value="true"),
            DeclareLaunchArgument("use_policy", default_value="false"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            # Parameter files; empty = the defaults packaged with control_arbiter. The application
            # passes the files it generates from the cell settings.
            DeclareLaunchArgument("arbiter_config", default_value=""),
            DeclareLaunchArgument("teleop_config", default_value=""),
            # Empty = use the value from the parameter file.
            DeclareLaunchArgument("source_timeout_ms", default_value=""),
            DeclareLaunchArgument("intent_validity_ms", default_value=""),
            OpaqueFunction(function=validate_policy_stage),
            OpaqueFunction(function=nodes),
            LogInfo(
                msg="mode=policy selected; no policy source is available in Stage 1",
                condition=IfCondition(PythonExpression(["'", mode, "' == 'policy'"])),
            ),
        ]
    )
