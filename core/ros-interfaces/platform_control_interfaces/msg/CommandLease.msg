# Observable command ownership grant. Arbitration behavior is out of scope.
unique_identifier_msgs/UUID lease_id
string<=64 owner_id
string<=64 target_id
builtin_interfaces/Time issued_at
builtin_interfaces/Time expires_at
