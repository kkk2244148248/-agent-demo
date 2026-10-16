"""一键启动 API（开发用）。"""
from __future__ import annotations

import uvicorn
from backend.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("backend.api.app:app", host=s.api_host, port=s.api_port, reload=False)
