cmake_minimum_required(VERSION 3.8)
project(camera_opencv)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
endif()
option(MRP_WARNINGS_AS_ERRORS "Treat compiler warnings as errors (CI)" OFF)
if(MRP_WARNINGS_AS_ERRORS)
  add_compile_options(-Werror)
endif()

find_package(ament_cmake REQUIRED)
find_package(mrp_camera_common REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core videoio)

add_executable(camera_node src/camera_node.cpp)
target_compile_features(camera_node PRIVATE cxx_std_17)
target_include_directories(camera_node PRIVATE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(camera_node
  mrp_camera_common::mrp_camera_common
  rclcpp::rclcpp
  ${sensor_msgs_TARGETS}
  opencv_core opencv_videoio
)

install(TARGETS camera_node
  DESTINATION lib/${PROJECT_NAME}
)
# Device probe used by the MRP backend (python3 /tools/camera_probe.py in the image).
install(PROGRAMS tools/camera_probe.py DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)

  ament_add_gtest(test_camera_utils test/test_camera_utils.cpp)
  target_compile_features(test_camera_utils PRIVATE cxx_std_17)
  target_include_directories(test_camera_utils PRIVATE include)
endif()

ament_package()
