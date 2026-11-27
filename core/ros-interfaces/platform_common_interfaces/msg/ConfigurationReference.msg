# Immutable reference to validated configuration stored outside this message.
string<=64 schema_id
string<=32 schema_version
string<=64 configuration_id
# Algorithm-prefixed content digest, for example "sha256:<hex>".
string<=128 content_hash
