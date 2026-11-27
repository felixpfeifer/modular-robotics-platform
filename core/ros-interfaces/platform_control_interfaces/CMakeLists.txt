cmake_minimum_required(VERSION 3.16)
project(platform_control_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(unique_identifier_msgs REQUIRED)
find_package(platform_common_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/TeleopState.msg"
  "msg/CartesianIntent.msg"
  "msg/JointIntent.msg"
  "msg/CommandLease.msg"
  "msg/CommandLeaseStatus.msg"
  "msg/BindingDescriptor.msg"
  "msg/BindingState.msg"
  "msg/SafetyStatus.msg"
  "msg/SafetyEvent.msg"
  "msg/CommandRejection.msg"
  "srv/AcquireCommandLease.srv"
  "srv/ReleaseCommandLease.srv"
  "srv/SetActiveBinding.srv"
  DEPENDENCIES
    builtin_interfaces
    std_msgs
    geometry_msgs
    unique_identifier_msgs
    platform_common_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
