"""Default settings for modular-flow-engine.

Maps to keys in config.example.yaml. Override via config.local.yaml.
"""

from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

# Platform-appropriate directories (resolved by platformdirs)
data_dir = Path(user_data_dir("modular-flow-engine"))
cache_dir = Path(user_cache_dir("modular-flow-engine"))

# Server defaults
server_host = "127.0.0.1"
server_port = 9847

# Execution defaults
execution_timeout = 300
execution_max_concurrent = 4
