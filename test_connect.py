"""Quick test: does pydobotplus connect, and if not, what error?"""

import logging
import time

logging.basicConfig(level=logging.DEBUG)

PORT = "COM6"

print(f"Connecting via pydobotplus on {PORT}...")
try:
    from pydobotplus import Dobot

    d = Dobot(port=PORT)
    print("SUCCESS — connected!")
    pose = d.get_pose()
    print(
        f"Pose: X={pose.position.x:.1f}  Y={pose.position.y:.1f}  Z={pose.position.z:.1f}"
    )
    d.close()
except Exception as e:
    print(f"\nFAILED: {type(e).__name__}: {e}")
