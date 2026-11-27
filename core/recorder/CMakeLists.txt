cmake_minimum_required(VERSION 3.8)
project(episode_recorder)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(rcutils REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosbag2_cpp REQUIRED)
find_package(rosbag2_storage REQUIRED)
find_package(rosbag2_transport REQUIRED)
find_package(platform_common_interfaces REQUIRED)
find_package(platform_control_interfaces REQUIRED)
find_package(platform_episode_interfaces REQUIRED)
find_package(nlohmann_json REQUIRED)

# ---------- Library (testable logic) ----------
add_library(episode_recorder_lib
  src/episode_manager.cpp
  src/keyboard_handler.cpp
)
target_include_directories(episode_recorder_lib PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(episode_recorder_lib
  rclcpp
  sensor_msgs
  std_msgs
  rosbag2_cpp
  rosbag2_storage
  rosbag2_transport
)

# ---------- Executable ----------
add_executable(recorder_node src/recorder_node.cpp)
target_link_libraries(recorder_node episode_recorder_lib)
ament_target_dependencies(recorder_node
  rclcpp
  rclcpp_action
  rcutils
  sensor_msgs
  std_msgs
  rosbag2_cpp
  rosbag2_storage
  rosbag2_transport
  platform_common_interfaces
  platform_control_interfaces
  platform_episode_interfaces
)
target_link_libraries(recorder_node nlohmann_json::nlohmann_json)

install(TARGETS recorder_node
  DESTINATION lib/${PROJECT_NAME}
)
install(TARGETS episode_recorder_lib
  DESTINATION lib
)
install(DIRECTORY include/
  DESTINATION include
)
install(DIRECTORY launch config scripts
  DESTINATION share/${PROJECT_NAME}
)
ament_python_install_package(episode_recorder_py)
install(PROGRAMS
  episode_recorder_py/validator_node.py
  episode_recorder_py/cleanup.py
  episode_recorder_py/export_lerobot.py
  episode_recorder_py/upload_lerobot.py
  episode_recorder_py/build_accepted_manifest.py
  episode_recorder_py/joint_intent_bridge.py
  episode_recorder_py/migrate_legacy.py
  episode_recorder_py/hil_qualification.py
  DESTINATION lib/${PROJECT_NAME}
)

# ---------- Tests ----------
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(ament_cmake_pytest REQUIRED)

  ament_add_gtest(test_episode_manager test/test_episode_manager.cpp)
  target_link_libraries(test_episode_manager episode_recorder_lib)
  ament_target_dependencies(test_episode_manager
    rclcpp
    sensor_msgs
    std_msgs
    rosbag2_cpp
    rosbag2_storage
  )

  ament_add_gtest(test_keyboard_handler test/test_keyboard_handler.cpp)
  target_link_libraries(test_keyboard_handler episode_recorder_lib)
  ament_target_dependencies(test_keyboard_handler rclcpp)

  ament_add_pytest_test(test_validation test/test_validation.py
    PYTHON_EXECUTABLE "${Python3_EXECUTABLE}"
  )
  ament_add_pytest_test(test_configuration test/test_configuration.py
    PYTHON_EXECUTABLE "${Python3_EXECUTABLE}"
  )
  ament_add_pytest_test(test_mcap_integration test/test_mcap_integration.py
    PYTHON_EXECUTABLE "${Python3_EXECUTABLE}"
    TIMEOUT 180
    ENV "PYTEST_ADDOPTS=--basetemp=${CMAKE_CURRENT_SOURCE_DIR}/.test-artifacts"
  )
  ament_add_pytest_test(test_joint_intent_bridge test/test_joint_intent_bridge.py
    PYTHON_EXECUTABLE "${Python3_EXECUTABLE}"
  )
  ament_add_pytest_test(test_cleanup test/test_cleanup.py
    PYTHON_EXECUTABLE "${Python3_EXECUTABLE}"
  )
endif()

ament_package()
