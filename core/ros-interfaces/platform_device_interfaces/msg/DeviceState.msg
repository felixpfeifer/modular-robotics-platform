# Observable device state at header.stamp. header.frame_id is normally empty.
std_msgs/Header header
string<=64 device_id

uint8 LIFECYCLE_UNKNOWN=0
uint8 LIFECYCLE_UNCONFIGURED=1
uint8 LIFECYCLE_INACTIVE=2
uint8 LIFECYCLE_ACTIVE=3
uint8 LIFECYCLE_FINALIZED=4
uint8 lifecycle_state

uint8 AVAILABILITY_UNKNOWN=0
uint8 AVAILABILITY_UNAVAILABLE=1
uint8 AVAILABILITY_DEGRADED=2
uint8 AVAILABILITY_AVAILABLE=3
uint8 availability

bool connected
# Standard summary; values must not contain secrets or bulk data.
diagnostic_msgs/DiagnosticStatus diagnostic
