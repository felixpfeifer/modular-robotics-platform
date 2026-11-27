cmake_minimum_required(VERSION 3.16)
project(platform_interface_transport_tests)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(platform_control_interfaces REQUIRED)

add_executable(teleop_cpp_publisher src/teleop_cpp_publisher.cpp)
ament_target_dependencies(teleop_cpp_publisher rclcpp platform_control_interfaces)

add_executable(teleop_cpp_subscriber src/teleop_cpp_subscriber.cpp)
ament_target_dependencies(teleop_cpp_subscriber rclcpp platform_control_interfaces)

install(TARGETS teleop_cpp_publisher teleop_cpp_subscriber
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(cross_language test/test_cross_language.py TIMEOUT 30)
  ament_add_pytest_test(service_and_action test/test_service_and_action.py TIMEOUT 30)
  ament_add_pytest_test(bounds test/test_bounds.py TIMEOUT 20)
  set_tests_properties(
    cross_language service_and_action bounds
    PROPERTIES ENVIRONMENT "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"
  )
endif()

ament_package()
