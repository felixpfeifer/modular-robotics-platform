cmake_minimum_required(VERSION 3.8)
project(mrp_camera_common)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
endif()
option(MRP_WARNINGS_AS_ERRORS "Treat compiler warnings as errors (CI)" OFF)
if(MRP_WARNINGS_AS_ERRORS)
  add_compile_options(-Werror)
endif()

find_package(ament_cmake REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(rclcpp REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)

# Header-only: drivers link mrp_camera_common::mrp_camera_common.
add_library(${PROJECT_NAME} INTERFACE)
target_compile_features(${PROJECT_NAME} INTERFACE cxx_std_17)
target_include_directories(${PROJECT_NAME} INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}>
)
target_link_libraries(${PROJECT_NAME} INTERFACE
  rclcpp::rclcpp
  ${diagnostic_msgs_TARGETS}
  ${rcl_interfaces_TARGETS}
  opencv_core opencv_imgcodecs opencv_imgproc
)

install(DIRECTORY include/ DESTINATION include/${PROJECT_NAME})
install(TARGETS ${PROJECT_NAME} EXPORT export_${PROJECT_NAME})
ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(diagnostic_msgs rcl_interfaces rclcpp OpenCV)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(sensor_msgs REQUIRED)

  ament_add_gtest(test_image test/test_image.cpp)
  target_link_libraries(test_image ${PROJECT_NAME})

  ament_add_gtest(test_frame_stats test/test_frame_stats.cpp)
  target_link_libraries(test_frame_stats ${PROJECT_NAME})

  # Fast DDS on localhost: the base image defaults to rmw_zenoh, which needs a router.
  ament_add_gtest(test_camera_node test/test_camera_node.cpp TIMEOUT 120
    ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  target_link_libraries(test_camera_node ${PROJECT_NAME} ${sensor_msgs_TARGETS})
endif()

ament_package()
