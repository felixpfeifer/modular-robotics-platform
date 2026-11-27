cmake_minimum_required(VERSION 3.16)
project(camera_manager LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(CAMERA_MANAGER_ENABLE_CPPCHECK "Run cppcheck as a build target" ON)

add_library(camera_manager_core
  src/camera_worker.cpp
  src/frame_synchronizer.cpp
)
target_include_directories(camera_manager_core PUBLIC include)
target_compile_features(camera_manager_core PUBLIC cxx_std_17)
target_compile_options(camera_manager_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
find_package(Threads REQUIRED)
target_link_libraries(camera_manager_core PUBLIC Threads::Threads)

find_package(ament_cmake QUIET)
find_package(rclcpp QUIET)
find_package(sensor_msgs QUIET)
find_package(OpenCV QUIET COMPONENTS core imgcodecs)

if(ament_cmake_FOUND AND rclcpp_FOUND AND sensor_msgs_FOUND AND OpenCV_FOUND)
  add_executable(camera_manager_node src/camera_manager_node.cpp)
  target_include_directories(camera_manager_node PRIVATE ${OpenCV_INCLUDE_DIRS})
  ament_target_dependencies(camera_manager_node rclcpp sensor_msgs)
  target_link_libraries(camera_manager_node camera_manager_core ${OpenCV_LIBS})
  install(TARGETS camera_manager_node DESTINATION lib/${PROJECT_NAME})
  install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})
else()
  message(STATUS "ROS 2 dependencies not found; building the hardware-free core only")
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(camera_manager_tests test/test_camera_manager.cpp)
  target_link_libraries(camera_manager_tests PRIVATE camera_manager_core)
  target_compile_options(camera_manager_tests PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  add_test(NAME camera_manager_tests COMMAND camera_manager_tests)
endif()

if(ament_cmake_FOUND)
  ament_package()
endif()

if(CAMERA_MANAGER_ENABLE_CPPCHECK)
  find_program(CPPCHECK_EXECUTABLE cppcheck)
  if(CPPCHECK_EXECUTABLE)
    add_custom_target(lint
      COMMAND ${CPPCHECK_EXECUTABLE} --enable=warning,style,performance,portability
        --error-exitcode=1 --std=c++17 --language=c++ --inline-suppr
        -I ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_SOURCE_DIR}/test
      WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
      COMMENT "Running cppcheck"
      VERBATIM)
  else()
    message(WARNING "cppcheck not found; lint target is unavailable")
  endif()
endif()
