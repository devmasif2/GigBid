"""Run the local GigSim stand-in: ``python -m gigsim_local``."""

import os

import uvicorn

from gigsim_local.app import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("GIGSIM_HOST", "127.0.0.1"),
        port=int(os.environ.get("GIGSIM_PORT", "8100")),
    )
