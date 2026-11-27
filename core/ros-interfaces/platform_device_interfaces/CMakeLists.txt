cmake_minimum_required(VERSION 3.16)
project(platform_device_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(platform_common_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/DeviceDescriptor.msg"
  "msg/DeviceState.msg"
  "msg/DeviceStateArray.msg"
  "msg/CalibrationReference.msg"
  "srv/ListDevices.srv"
  "srv/GetDeviceState.srv"
  DEPENDENCIES std_msgs diagnostic_msgs platform_common_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
