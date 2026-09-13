#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m grpc_tools.protoc \
    -I proto \
    --python_out=proto \
    --grpc_python_out=proto \
    proto/agent.proto
sed -i 's/import agent_pb2/from proto import agent_pb2/' proto/agent_pb2_grpc.py
echo "Generated proto/agent_pb2.py and proto/agent_pb2_grpc.py"
