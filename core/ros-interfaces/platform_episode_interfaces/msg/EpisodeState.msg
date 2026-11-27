# Observable lifecycle state for one episode recording or processing run.
std_msgs/Header header
unique_identifier_msgs/UUID episode_id
string<=64 task_id

uint8 STATE_UNKNOWN=0
uint8 STATE_PENDING=1
uint8 STATE_RECORDING=2
uint8 STATE_FINALIZING=3
uint8 STATE_RECORDED=4
uint8 STATE_VALIDATING=5
uint8 STATE_VALIDATED=6
uint8 STATE_FAILED=7
uint8 STATE_CANCELED=8
uint8 state

uint16 reason_code
string<=256 summary
