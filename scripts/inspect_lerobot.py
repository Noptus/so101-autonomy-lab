"""Inspect installed interfaces; never open a device."""

import inspect
import importlib.metadata
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

print("LeRobot", importlib.metadata.version("lerobot"))
print("SO101FollowerConfig", inspect.signature(SO101FollowerConfig))
for method in ("connect", "get_observation", "send_action", "configure", "disconnect"):
    print(method, inspect.signature(getattr(SO101Follower, method)))
