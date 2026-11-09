# Air Control

Control the mouse with hand gestures tracked by your webcam.

## Requirements

- Windows
- Python 3.12
- A webcam

## Setup

From the project folder, run:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then start the app with `run_air_control.bat`, or run:

```bat
.venv\Scripts\python.exe air_control.py
```

Use `--camera 1` to select another camera, or `--no-preview` to hide the preview window. With preview enabled, press **q** in the window to quit; you can also press **Ctrl+C** in the terminal.

## Gestures

Use one hand with your palm facing the camera:

| Gesture | Action |
| --- | --- |
| Index finger up | Move the cursor |
| Pinch thumb and index finger | Click; hold and move to drag |
| Pinch thumb and middle finger | Right-click |
| Index and middle fingers up | Scroll |
| Closed fist | Pause control |

This app can move and click your mouse. Keep the keyboard accessible so you can stop it with **q** or **Ctrl+C**.
