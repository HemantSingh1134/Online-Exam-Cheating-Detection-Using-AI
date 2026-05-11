import cv2
import mediapipe as mp
import numpy as np

# Initialize MediaPipe Face Detection and Face Mesh
mp_face_detection = mp.solutions.face_detection
mp_drawing = mp.solutions.drawing_utils
mp_face_mesh = mp.solutions.face_mesh

# Initialize face detection and face mesh models
face_detection = mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
face_mesh = mp_face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5)

def detectFace(frame):
    """
    Detects faces, landmarks, and alerts on suspicious activities (e.g., multiple faces or suspicious gaze).
    Returns: faceCount, annotated frame
    """
    # Convert the frame to RGB as required by MediaPipe
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faceCount = 0

    # Detect faces in the frame
    detection_results = face_detection.process(rgb_frame)
    annotated_frame = frame.copy()

    if detection_results.detections:
        faceCount = len(detection_results.detections)

        # Draw bounding boxes and landmarks
        for detection in detection_results.detections:
            mp_drawing.draw_detection(annotated_frame, detection)

    # Alert for multiple faces
    if faceCount > 1:
        cv2.putText(annotated_frame, 'Alert: Multiple Faces Detected!', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    # Detect facial landmarks using Face Mesh
    mesh_results = face_mesh.process(rgb_frame)
    if mesh_results.multi_face_landmarks:
        for face_landmarks in mesh_results.multi_face_landmarks:
            # Draw the facial landmarks on the frame
            mp_drawing.draw_landmarks(
                image=annotated_frame,
                landmark_list=face_landmarks,
                connections=mp_face_mesh.FACEMESH_TESSELATION,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=1, circle_radius=1)
            )

    return faceCount, annotated_frame


# if __name__ == "__main__":
#     cap = cv2.VideoCapture(0)
#     if not cap.isOpened():
#         print("Error: Could not open camera.")
#         exit()

#     print("Press 'q' to exit.")
#     while True:
#         ret, frame = cap.read()
#         if not ret:
#             print("Error: Unable to fetch frame.")
#             break

#         faceCount, annotated_frame = detectFace(frame)
#         cv2.imshow('Facial Detection and Monitoring', annotated_frame)

#         # Quit the application on pressing 'q'
#         if cv2.waitKey(1) & 0xFF == ord('q'):
#             break

#     cap.release()
#     cv2.destroyAllWindows()
