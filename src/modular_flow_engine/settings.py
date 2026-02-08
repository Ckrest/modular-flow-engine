"""Default settings for modular-flow-engine.

Maps to keys in config.example.yaml. Override via config.local.yaml.
"""

from pathlib import Path

# Standard XDG directories
data_dir = Path("~/.local/share/modular-flow-engine").expanduser()
cache_dir = Path("~/.cache/modular-flow-engine").expanduser()

# Server defaults
server_host = "127.0.0.1"
server_port = 9847

# Execution defaults
execution_timeout = 300
execution_max_concurrent = 4
