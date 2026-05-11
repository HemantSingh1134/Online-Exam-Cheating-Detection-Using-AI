import cv2
import numpy as np
import mediapipe as mp

# Initialize MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(refine_landmarks=True)

def gaze_tracking(frame):
    """Detect gaze direction (left, right, center)."""
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(frame_rgb)

    if results.multi_face_landmarks:
        for landmarks in results.multi_face_landmarks:
            # Get left and right eye landmarks
            left_eye = [landmarks.landmark[33], landmarks.landmark[159]]  # Left eye corners
            right_eye = [landmarks.landmark[362], landmarks.landmark[386]]  # Right eye corners

            # Calculate horizontal gaze direction
            left_eye_center = np.mean([(p.x, p.y) for p in left_eye], axis=0)
            right_eye_center = np.mean([(p.x, p.y) for p in right_eye], axis=0)

            gaze_direction = "center"
            if left_eye_center[0] < 0.4:  # Left threshold
                gaze_direction = "left"
            elif right_eye_center[0] > 0.6:  # Right threshold
                gaze_direction = "right"

            return {"gaze": gaze_direction}

    return {"gaze": "center"}