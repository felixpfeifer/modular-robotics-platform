cmake_minimum_required(VERSION 3.16)
project(platform_interface_consumer_fixture)

find_package(ament_cmake REQUIRED)
find_package(platform_common_interfaces REQUIRED)
find_package(platform_device_interfaces REQUIRED)
find_package(platform_control_interfaces REQUIRED)
find_package(platform_episode_interfaces REQUIRED)

add_executable(consumer_fixture src/consumer_fixture.cpp)
ament_target_dependencies(consumer_fixture
  platform_common_interfaces
  platform_device_interfaces
  platform_control_interfaces
  platform_episode_interfaces
)

if(BUILD_TESTING)
  add_test(NAME consumer_fixture_constructs_types COMMAND consumer_fixture)
endif()

install(TARGETS consumer_fixture DESTINATION lib/${PROJECT_NAME})
ament_package()
