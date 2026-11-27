cmake_minimum_required(VERSION 3.8)
project(camera_ids)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
endif()
option(MRP_WARNINGS_AS_ERRORS "Treat compiler warnings as errors (CI)" OFF)
if(MRP_WARNINGS_AS_ERRORS)
  add_compile_options(-Werror)
endif()

# The IDS Software Suite (uEye API) cannot be downloaded without an IDS account,
# so CI builds and tests the SDK-free helpers only. The Docker image sets this ON.
option(CAMERA_IDS_REQUIRE_SDK "Fail if the IDS uEye SDK is not installed" OFF)

find_package(ament_cmake REQUIRED)
find_package(mrp_camera_common REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core)

find_path(UEYE_INCLUDE_DIR ueye.h PATHS /usr/include /usr/local/include /opt/ids/ueye/include)
find_library(UEYE_LIBRARY NAMES ueye_api PATHS /usr/lib /usr/local/lib /opt/ids/ueye/lib)

if(UEYE_INCLUDE_DIR AND UEYE_LIBRARY)
  message(STATUS "IDS uEye SDK: ${UEYE_LIBRARY}")
  add_executable(camera_node src/ids_node.cpp)
  target_compile_features(camera_node PRIVATE cxx_std_17)
  target_include_directories(camera_node PRIVATE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  # The SDK header is not ours to keep warning-free.
  target_include_directories(camera_node SYSTEM PRIVATE ${UEYE_INCLUDE_DIR})
  target_link_libraries(camera_node
    mrp_camera_common::mrp_camera_common
    rclcpp::rclcpp
    ${sensor_msgs_TARGETS}
    opencv_core
    ${UEYE_LIBRARY}
  )
  install(TARGETS camera_node DESTINATION lib/${PROJECT_NAME})
elseif(CAMERA_IDS_REQUIRE_SDK)
  message(FATAL_ERROR "IDS uEye SDK (ueye.h, libueye_api) not found. Install the IDS Software Suite.")
else()
  message(WARNING "IDS uEye SDK not found: camera_node is NOT built (helpers and tests only).")
endif()

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_ids_utils test/test_ids_utils.cpp)
  target_compile_features(test_ids_utils PRIVATE cxx_std_17)
  target_include_directories(test_ids_utils PRIVATE include)
endif()

ament_package()
