"""
Air Control - control your computer with hand gestures seen by the webcam.

Gestures (use ONE hand, palm facing the camera):
  Index finger up ............ move the mouse cursor
  Pinch thumb + index ........ left click (hold the pinch and move = drag)
  Pinch thumb + middle ....... right click
  Index + middle up (peace) .. scroll (move hand up / down)
  Closed fist ................ PAUSE (nothing is controlled)

Keys in the preview window:  q = quit
"""

import argparse
import math
import sys
import time

import cv2
import numpy as np
import pyautogui

try:
    import mediapipe as mp
    if not hasattr(mp, "solutions"):
        raise ImportError("The installed MediaPipe package is missing the legacy 'solutions' API.")
except ImportError as exc:
    raise SystemExit(
        "MediaPipe is not set up correctly for this app.\n"
        "Use Python 3.12 and run:\n"
        "  py -3.12 -m pip install -r requirements.txt\n"
        "  py -3.12 air_control.py"
    ) from exc

# ---------------- settings you can tweak ----------------
CAM_W, CAM_H = 480, 360       # camera capture and processing size
FRAME_MARGIN = 80             # dead border (px): hand only needs to move inside the inner box
SMOOTHING = 2.5               # lower = cursor follows the hand more quickly
MAX_CURSOR_STEP = 45          # cap jumps while allowing faster cursor movement
PINCH_ON = 0.32               # pinch starts below this (relative to palm size)
PINCH_OFF = 0.48              # pinch ends above this (hysteresis avoids flicker)
LEFT_PINCH_ON = 0.55          # left click is easier to trigger than right click
LEFT_PINCH_OFF = 0.70
DRAG_DEADZONE = 12            # hand must move this far before a held pinch drags
SCROLL_GAIN = 900             # higher = faster scrolling
RIGHT_CLICK_COOLDOWN = 0.8    # seconds between right clicks
# --------------------------------------------------------

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False    # cursor must be able to reach screen corners

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

TIP = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIP = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def fingers_up(lm):
    """Return dict of which four fingers are extended (hand upright)."""
    return {name: lm[TIP[name]].y < lm[PIP[name]].y for name in PIP}


class AirControl:
    def __init__(self, camera=0, preview=True):
        import sys
        if sys.platform.startswith("win"):
            # DirectShow avoids black/empty frames on many Windows webcams
            self.cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(camera)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open the camera. Try --camera 1.")
        self.preview = preview
        self.screen_w, self.screen_h = pyautogui.size()
        self.hands = mp_hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.prev_x, self.prev_y = pyautogui.position()
        self.left_down = False
        self.left_pinch_active = False
        self.left_dragging = False
        self.left_press_wrist = None
        self.left_press_cursor = None
        self.last_right_click = 0.0
        self.prev_scroll_y = None
        self.scroll_accum = 0.0
        self.pinch_ratio = None
        self.mode = "NO HAND"
        self.startup_time = time.monotonic()

    # ---------- actions ----------
    def move_cursor(self, lm, w, h):
        x = lm[TIP["index"]].x * w
        y = lm[TIP["index"]].y * h
        sx = np.interp(x, (FRAME_MARGIN, w - FRAME_MARGIN), (0, self.screen_w - 1))
        sy = np.interp(y, (FRAME_MARGIN, h - FRAME_MARGIN), (0, self.screen_h - 1))
        cx = self.prev_x + (sx - self.prev_x) / SMOOTHING
        cy = self.prev_y + (sy - self.prev_y) / SMOOTHING
        dx, dy = cx - self.prev_x, cy - self.prev_y
        distance = math.hypot(dx, dy)
        if distance > MAX_CURSOR_STEP:
            scale = MAX_CURSOR_STEP / distance
            cx = self.prev_x + dx * scale
            cy = self.prev_y + dy * scale
        cx = min(max(cx, 0), self.screen_w - 1)
        cy = min(max(cy, 0), self.screen_h - 1)
        pyautogui.moveTo(cx, cy)
        self.prev_x, self.prev_y = cx, cy

    def release_left(self):
        if self.left_down:
            pyautogui.mouseUp()
            self.left_down = False
        self.left_pinch_active = False
        self.left_dragging = False
        self.left_press_wrist = None
        self.left_press_cursor = None

    def move_drag(self, lm, w, h):
        wrist_x, wrist_y = self.left_press_wrist
        origin_x, origin_y = self.left_press_cursor
        dx = (lm[0].x - wrist_x) * w
        dy = (lm[0].y - wrist_y) * h
        distance = math.hypot(dx, dy)
        if distance <= DRAG_DEADZONE:
            return False

        scale_x = self.screen_w / max(w - 2 * FRAME_MARGIN, 1)
        scale_y = self.screen_h / max(h - 2 * FRAME_MARGIN, 1)
        move_x = dx * (distance - DRAG_DEADZONE) / distance
        move_y = dy * (distance - DRAG_DEADZONE) / distance
        target_x = min(max(origin_x + move_x * scale_x, 0), self.screen_w - 1)
        target_y = min(max(origin_y + move_y * scale_y, 0), self.screen_h - 1)
        current_x, current_y = pyautogui.position()
        if not self.left_down:
            pyautogui.mouseDown()
            self.left_down = True
        self.left_dragging = True
        step_x, step_y = target_x - current_x, target_y - current_y
        step_distance = math.hypot(step_x, step_y)
        if step_distance > MAX_CURSOR_STEP:
            scale = MAX_CURSOR_STEP / step_distance
            target_x = current_x + step_x * scale
            target_y = current_y + step_y * scale
        pyautogui.moveTo(target_x, target_y)
        self.prev_x, self.prev_y = target_x, target_y
        return True

    def finish_left_pinch(self):
        if self.left_pinch_active and not self.left_dragging:
            pyautogui.click()
        self.release_left()

    def handle_scroll(self, lm):
        y = (lm[TIP["index"]].y + lm[TIP["middle"]].y) / 2
        if self.prev_scroll_y is not None:
            # hand moves up -> scroll up
            self.scroll_accum += (self.prev_scroll_y - y) * SCROLL_GAIN
            steps = int(self.scroll_accum)
            if steps:
                pyautogui.scroll(steps)
                self.scroll_accum -= steps
        self.prev_scroll_y = y

    def draw_startup_animation(self, frame):
        elapsed = time.monotonic() - self.startup_time
        duration = 2.5
        if elapsed >= duration:
            return

        h, w = frame.shape[:2]
        progress = elapsed / duration
        overlay = frame.copy()
        center = (w // 2, h // 2)
        pulse = int(5 * math.sin(elapsed * 7))
        radius = 38 + pulse
        cv2.circle(overlay, center, radius, (255, 170, 45), 2, cv2.LINE_AA)
        cv2.ellipse(
            overlay,
            center,
            (radius + 12, radius + 12),
            -90,
            0,
            int(360 * min(progress * 1.5, 1.0)),
            (80, 235, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            "AIR CONTROL",
            (w // 2 - 95, h // 2 + 76),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            "Starting hand tracking...",
            (w // 2 - 94, h // 2 + 101),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (210, 230, 235),
            1,
            cv2.LINE_AA,
        )
        bar_left, bar_right = w // 2 - 80, w // 2 + 80
        bar_y = h // 2 + 116
        cv2.rectangle(overlay, (bar_left, bar_y), (bar_right, bar_y + 4), (90, 90, 90), -1)
        cv2.rectangle(
            overlay,
            (bar_left, bar_y),
            (bar_left + int((bar_right - bar_left) * progress), bar_y + 4),
            (80, 235, 255),
            -1,
        )
        cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)

    # ---------- per-frame logic ----------
    def process(self, lm, w, h):
        palm = max(dist(lm[0], lm[9]), 1e-6)  # wrist -> middle knuckle = hand size
        pinch_idx = dist(lm[TIP["thumb"]], lm[TIP["index"]]) / palm
        pinch_mid = dist(lm[TIP["thumb"]], lm[TIP["middle"]]) / palm
        self.pinch_ratio = pinch_idx
        up = fingers_up(lm)

        if self.left_pinch_active and pinch_idx > LEFT_PINCH_OFF:
            was_dragging = self.left_dragging
            self.finish_left_pinch()
            self.mode = "DRAG" if was_dragging else "CLICK"
            return

        # Fist = pause
        if not any(up.values()) and pinch_idx > PINCH_OFF and pinch_mid > PINCH_OFF:
            self.release_left()
            self.prev_scroll_y = None
            self.mode = "PAUSED (fist)"
            return

        # Scroll: index + middle up, ring + pinky down, no pinch
        if (up["index"] and up["middle"] and not up["ring"] and not up["pinky"]
                and pinch_idx > PINCH_OFF and pinch_mid > PINCH_OFF):
            self.release_left()
            self.handle_scroll(lm)
            self.mode = "SCROLL"
            return
        self.prev_scroll_y = None
        self.scroll_accum = 0.0

        # Right click: thumb + middle pinch (index not pinching)
        now = time.time()
        if pinch_mid < PINCH_ON and pinch_idx > PINCH_OFF:
            self.release_left()
            if now - self.last_right_click > RIGHT_CLICK_COOLDOWN:
                pyautogui.click(button="right")
                self.last_right_click = now
            self.mode = "RIGHT CLICK"
            return

        # A stationary pinch clicks on release; moving the wrist past the deadzone drags.
        if self.left_pinch_active:
            self.move_drag(lm, w, h)
            self.mode = "DRAG" if self.left_dragging else "CLICK"
        elif pinch_idx < LEFT_PINCH_ON:
            self.left_pinch_active = True
            self.left_press_wrist = (lm[0].x, lm[0].y)
            self.left_press_cursor = pyautogui.position()
            self.mode = "CLICK"
        elif up["index"]:
            self.move_cursor(lm, w, h)
            self.mode = "MOVE"
        else:
            self.mode = "IDLE"

    def run(self):
        print("Air Control running. Press 'q' in the window (or Ctrl+C) to quit.")
        try:
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    break
                frame = cv2.flip(frame, 1)  # mirror so it feels natural
                if frame.shape[1] != CAM_W or frame.shape[0] != CAM_H:
                    frame = cv2.resize(frame, (CAM_W, CAM_H), interpolation=cv2.INTER_AREA)
                h, w = frame.shape[:2]
                result = self.hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                if result.multi_hand_landmarks:
                    hand = result.multi_hand_landmarks[0]
                    self.process(hand.landmark, w, h)
                    if self.preview:
                        mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)
                else:
                    self.release_left()
                    self.prev_scroll_y = None
                    self.pinch_ratio = None
                    self.mode = "NO HAND"

                if self.preview:
                    cv2.rectangle(frame, (FRAME_MARGIN, FRAME_MARGIN),
                                  (w - FRAME_MARGIN, h - FRAME_MARGIN), (255, 0, 255), 2)
                    cv2.putText(frame, self.mode, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                    brightness = float(frame.mean())
                    if brightness < 50:
                        cv2.putText(frame, "TOO DARK - add light / face a window", (10, 65),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    elif self.mode == "NO HAND":
                        cv2.putText(frame, "Show your open hand, 40-70 cm away", (10, 65),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                    if self.pinch_ratio is not None:
                        cv2.putText(
                            frame,
                            f"Left pinch gap: {self.pinch_ratio:.2f} (pinch < {LEFT_PINCH_ON:.2f}, release > {LEFT_PINCH_OFF:.2f})",
                            (10, 100),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 0),
                            2,
                        )
                    self.draw_startup_animation(frame)
                    cv2.imshow("Air Control  (q to quit)", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.release_left()
            self.cap.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Control your computer with hand gestures.")
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument("--no-preview", action="store_true", help="hide the camera window")
    args = parser.parse_args()
    AirControl(camera=args.camera, preview=not args.no_preview).run()
