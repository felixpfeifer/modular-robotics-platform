cmake_minimum_required(VERSION 3.16)
project(platform_episode_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(unique_identifier_msgs REQUIRED)
find_package(platform_common_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/EpisodeState.msg"
  "msg/EpisodeEvent.msg"
  "msg/EpisodeMetadata.msg"
  "msg/ValidationFinding.msg"
  "srv/MarkEpisode.srv"
  "action/RecordEpisode.action"
  "action/ValidateEpisode.action"
  DEPENDENCIES
    builtin_interfaces
    std_msgs
    unique_identifier_msgs
    platform_common_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
