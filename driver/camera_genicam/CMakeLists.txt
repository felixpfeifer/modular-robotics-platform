cmake_minimum_required(VERSION 3.8)
project(camera_genicam)

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
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)
# Aravis (GenICam: GigE Vision + USB3 Vision), LGPL-2.1+, from Ubuntu: libaravis-dev.
find_package(PkgConfig REQUIRED)
pkg_check_modules(ARAVIS REQUIRED IMPORTED_TARGET aravis-0.8>=0.8.25)

add_executable(camera_node src/genicam_node.cpp)
target_compile_features(camera_node PRIVATE cxx_std_17)
target_include_directories(camera_node PRIVATE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(camera_node
  mrp_camera_common::mrp_camera_common
  rclcpp::rclcpp
  ${sensor_msgs_TARGETS}
  opencv_core opencv_imgproc
  PkgConfig::ARAVIS
)
install(TARGETS camera_node DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_genicam_utils test/test_genicam_utils.cpp)
  target_compile_features(test_genicam_utils PRIVATE cxx_std_17)
  target_include_directories(test_genicam_utils PRIVATE include)
  target_link_libraries(test_genicam_utils ${OpenCV_LIBS})

  # The real node against Aravis' in-process fake GigE camera. Fast DDS, because
  # rmw_zenoh needs a router that test runners do not have.
  find_package(ament_cmake_test REQUIRED)
  set(_smoke_result "${AMENT_TEST_RESULTS_DIR}/${PROJECT_NAME}/fake_camera_smoke.xunit.xml")
  ament_add_test(fake_camera_smoke
    COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/test/fake_camera_smoke.py --node $<TARGET_FILE:camera_node>
      --junit ${_smoke_result}
    RESULT_FILE ${_smoke_result}
    TIMEOUT 90
    ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
  )
endif()

ament_package()
