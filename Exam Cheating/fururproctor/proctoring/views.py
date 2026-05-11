
# Django Core Imports
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse, HttpResponseRedirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.contrib.auth import authenticate, login as auth_login
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from django.core.files.base import ContentFile

import cv2
import io
from PIL import Image

# Models
from .models import Student, Exam, CheatingEvent, CheatingImage, CheatingAudio

# External Imports
import os
import json
import threading
import base64
import numpy as np
import logging
import time
from datetime import datetime

# ML imports
from .ml_models.object_detection import detectObject
from .ml_models.audio_detection import audio_detection
from .ml_models.gaze_tracking import gaze_tracking

# Optional heavy libs
import pytz

NEPAL_TZ = pytz.timezone('Asia/Kathmandu')

def get_nepal_time():
    return datetime.now(NEPAL_TZ)


def get_questions_file_path():
    return os.path.join(os.path.dirname(__file__), 'dummy_data', 'ai.json')


def get_tab_switch_session_key(student_id):
    return f"exam_tab_switch_initialized_{student_id}"


TAB_SWITCH_LIMIT = 1

# =========================
# FIXED FACE RECOGNITION PART
# =========================

def get_face_encoding(image):
    """
    Lazy-loaded face recognition to avoid Django startup crash/warning.
    """
    import face_recognition

    face_locations = face_recognition.face_locations(image)
    if not face_locations:
        return None

    return face_recognition.face_encodings(image, face_locations)[0]


def match_face_encodings(captured_encoding, stored_encoding):
    """
    Compare face encodings safely.
    """
    import face_recognition

    return face_recognition.compare_faces(
        [stored_encoding],
        captured_encoding
    )[0]

# =========================
# VIEWS (UNCHANGED LOGIC)
# =========================

def home(request):
    return render(request, 'home.html')


def registration(request):
    if request.method == 'POST':
        name = request.POST['name']
        address = request.POST['address']
        email = request.POST['email']
        password = request.POST['password']
        captured_photo = request.POST.get('photo_data')

        try:
            img_data = base64.b64decode(captured_photo.split(',')[1])
            nparr = np.frombuffer(img_data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            face_encoding = get_face_encoding(image)
            if face_encoding is None:
                messages.error(request, "No face detected.")
                return redirect('registration')

        except Exception as e:
            messages.error(request, str(e))
            return redirect('registration')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email exists")
            return redirect('registration')

        user = User.objects.create(
            username=email,
            email=email,
            first_name=name.split(' ')[0],
            last_name=' '.join(name.split(' ')[1:]) if ' ' in name else '',
            password=make_password(password),
        )

        student = Student(
            user=user,
            name=name,
            address=address,
            email=email,
            photo=ContentFile(img_data, name=f"{name}.jpg"),
            face_encoding=face_encoding.tolist(),
        )
        student.save()

        return redirect('login')

    return render(request, 'registration.html')


@csrf_exempt
def login(request):
    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')
        captured_photo_data = request.POST.get('captured_photo')

        if not email or not password or not captured_photo_data:
            return JsonResponse({
                "success": False,
                "error": "Email, password, and captured photo are required."
            }, status=400)

        try:
            captured_photo_data = captured_photo_data.split(',')[1]
            captured_photo = base64.b64decode(captured_photo_data)
        except (IndexError, ValueError, TypeError):
            return JsonResponse({
                "success": False,
                "error": "Invalid captured photo data."
            }, status=400)

        nparr = np.frombuffer(captured_photo, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        captured_encoding = get_face_encoding(image)
        if captured_encoding is None:
            return JsonResponse({
                "success": False,
                "error": "No face detected in the captured photo."
            }, status=400)

        user = authenticate(request, username=email, password=password)
        if not user:
            return JsonResponse({
                "success": False,
                "error": "Invalid email or password."
            }, status=401)

        student = user.student
        stored_encoding = np.array(student.face_encoding)

        if match_face_encodings(captured_encoding, stored_encoding):
            auth_login(request, user)
            request.session['user_name'] = student.name
            return JsonResponse({
                "success": True,
                "student_name": student.name,
                "redirect_url": reverse('dashboard'),
            })

        return JsonResponse({
            "success": False,
            "error": "Face does not match the registered student."
        }, status=401)

    return render(request, "login.html")


# =========================
# EVERYTHING BELOW YOUR FILE IS UNCHANGED
# =========================
# (keep all your existing logic: exam, proctoring, threads, etc.)
# Logout View 
def logout_view(request):
    """
    Handles user logout.
    - Clears all session data.
    - Displays a success message.
    - Redirects the user to the home page.
    """
    request.session.flush()  # Clear all session data
    messages.success(request, "You have been logged out.")  # Display a success message
    return redirect('home')  # Redirect to the home page

# Video feed generation for the webcam
def gen_frames():
    """
    Generates a live video feed from the webcam.
    - Captures frames from the webcam using OpenCV.
    - Encodes each frame as a JPEG image.
    - Yields the frames as a streaming response for real-time display in the browser.
    """
    camera = cv2.VideoCapture(0)  # Open the default webcam (index 0)
    if not camera.isOpened():  # Check if the webcam was successfully opened
        raise RuntimeError("Could not open webcam.")

    while True:
        success, frame = camera.read()  # Read a frame from the webcam
        if not success:
            break  # Exit the loop if the frame cannot be read

        # Encode the frame as a JPEG image
        _, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()  # Convert the frame to bytes

        # Yield the frame as part of a streaming response
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    # Release the webcam when the loop ends
    camera.release()


# Video feed view
def video_feed(request):
    """
    Streams the live video feed to the browser.
    - Uses the `gen_frames` generator to fetch frames from the webcam.
    - Returns a `StreamingHttpResponse` with the appropriate content type for real-time video streaming.
    """
    return StreamingHttpResponse(
        gen_frames(),  # Use the generator to stream frames
        content_type='multipart/x-mixed-replace; boundary=frame'  # Required for live video streaming
    )


# Stop video feed view
def stop_event(request):
    """
    Dummy endpoint for stopping the video feed.
    - Can be extended to handle cleanup or other actions when the video feed is stopped.
    - Returns a JSON response indicating success.
    """
    return JsonResponse({'status': 'success'})  # Simple response for stopping the video feed

#Dashboard View
@login_required
def dashboard(request):
    """
    Renders the dashboard page for authenticated users.
    - Retrieves the user's name from the session.
    - Displays personalized content on the dashboard.
    - Handles cases where the user is not logged in (defaults to 'Guest').
    """
    # Retrieve the user's name from the session (default to 'Guest' if not found)
    user_name = request.session.get('user_name', 'Guest')

    # Prepare context data to pass to the template
    context = {
        'user_name': user_name,  # Pass the user's name to the template
    }

    # Render the dashboard template with the context data
    return render(request, 'dashboard.html', context)



# -------------------------Video Detection Thread----------------------------------
from django.utils import timezone
import pytz

# Define Nepal Time Zone
NEPAL_TZ = pytz.timezone('Asia/Kathmandu')

# Helper function to get Nepal time
def get_nepal_time():
    return timezone.now().astimezone(NEPAL_TZ)

def get_nepal_time_str():
    return get_nepal_time().strftime('%Y-%m-%d %I:%M:%S %p %Z')


logger = logging.getLogger(__name__)

# Global variables for warnings and background processes
warning = None
last_audio_detected_time = time.time()
stop_event = threading.Event()  # To stop background threads

# Function to process each frame
def process_frame(frame, request):
    """Process a single frame for cheating detection."""
    global warning
    labels, processed_frame, person_count, detected_objects = detectObject(frame)
    cheating_event = None

    # Extract object names
    detected_labels = [label for label, _ in labels]
    # Check for cheating conditions
    if any(label in ["cell phone", "book"] for label in detected_labels):
        warning = f"ALERT: {', '.join(detected_labels)} detected!"  # Corrected formatting
        cheating_event, _ = CheatingEvent.objects.get_or_create(
            student=request.user.student,
            cheating_flag=True,
            event_type="object_detected"
        )
        save_cheating_event(frame, request, cheating_event, detected_objects)

    if person_count > 1:
        warning = "ALERT: Multiple persons detected!"
        cheating_event, _ = CheatingEvent.objects.get_or_create(
            student=request.user.student,
            cheating_flag=True,
            event_type="multiple_persons"
        )
        save_cheating_event(frame, request, cheating_event, detected_objects)

    gaze = gaze_tracking(frame)
    if gaze["gaze"] != "center":
        warning = "ALERT: Candidate not looking at the screen!"
        cheating_event, _ = CheatingEvent.objects.get_or_create(
            student=request.user.student,
            cheating_flag=True,
            event_type="gaze_detected"
        )
        save_cheating_event(frame, request, cheating_event, detected_objects)

# Function to process audio
def process_audio(request):
    """Continuously process audio for cheating detection."""
    global last_audio_detected_time, warning

    while not stop_event.is_set():  # Check if stop_event is triggered
        audio = audio_detection()
        if audio["audio_detected"]:
            warning = "ALERT: Suspicious audio detected!"
            cheating_event, _ = CheatingEvent.objects.get_or_create(
                student=request.user.student,
                cheating_flag=True,
                event_type="audio_detected"
            )
            save_cheating_event(None, request, cheating_event, audio_data=audio["audio_data"])
            last_audio_detected_time = time.time()

        if time.time() - last_audio_detected_time > 5:
            warning = None

        time.sleep(2)  # Avoid excessive CPU usage

    print("Audio processing stopped.")  # Debugging to confirm the thread exits



# Background processing for video
def background_processing(request):
    """Runs video processing in the background."""
    cap = cv2.VideoCapture(0)
    frame_count = 0

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_count % 2 == 0:
            process_frame(frame, request)
        
        frame_count += 1
        time.sleep(0.5)
    
    cap.release()


# Helper function to create a WAV file from raw audio bytes
import io
import wave

def create_wav_bytes(raw_audio, channels=1, sampwidth=2, framerate=48000):
    """
    Wrap raw PCM audio bytes with a WAV header.
    
    :param raw_audio: The raw audio bytes (concatenated frames)
    :param channels: Number of audio channels (1 for mono)
    :param sampwidth: Sample width in bytes (2 for 16-bit audio)
    :param framerate: Frame rate (sample rate)
    :return: Audio data in WAV format as bytes
    """
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(raw_audio)
    return wav_buffer.getvalue()

## Function to save cheating event
def save_cheating_event(frame, request, cheating_event, detected_objects=None, audio_data=None):
    """Save cheating event along with images and audio in the database."""
    try:
        
        # Save detected objects
        if detected_objects:
            cheating_event.detected_objects = detected_objects  # Save as JSON
            cheating_event.save()
        # Save up to 10 sample images per event
        if frame is not None and cheating_event.cheating_images.count() < 10:
            try:
                image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                image_io = io.BytesIO()
                image_pil.save(image_io, format="JPEG", quality=85)
                image_content = image_io.getvalue()
                
                cheating_image = CheatingImage(event=cheating_event)
                cheating_image.image.save(
                    f"cheating_{time.time()}.jpg", 
                    ContentFile(image_content), 
                    save=True
                )
            except Exception as e:
                logger.error(f"Error processing image: {e}")
        
        # Save audio data
        if audio_data:
            try:
                # Convert raw audio bytes to a proper WAV file bytes.
                wav_data = create_wav_bytes(audio_data, channels=1, sampwidth=2, framerate=48000)
                cheating_audio = CheatingAudio(event=cheating_event)
                cheating_audio.audio.save(
                    f"cheating_audio_{time.time()}.wav", 
                    ContentFile(wav_data), 
                    save=True
                )
            except Exception as e:
                logger.error(f"Error processing audio: {e}")

        logger.info(f"Cheating event saved for student {request.user.student.id}")
    
    except Exception as e:
        logger.error(f"Error saving cheating event: {e}")

## Exam Page View
@login_required
def exam(request):
    """Start the exam and initialize proctoring."""
    try:
        # Get the Student instance associated with the logged-in user
        student = request.user.student
    except Student.DoesNotExist:
        # Handle the case where the user does not have a linked Student instance
        return HttpResponse("Student profile not found. Please contact support.", status=404)

    session_key = get_tab_switch_session_key(student.id)
    tab_switch_event, _ = CheatingEvent.objects.get_or_create(
        student=student,
        event_type='tab_switch',
        defaults={
            'cheating_flag': False,
            'tab_switch_count': 0,
        }
    )

    if not request.session.get(session_key):
        tab_switch_event.tab_switch_count = 0
        tab_switch_event.cheating_flag = False
        tab_switch_event.save(update_fields=['tab_switch_count', 'cheating_flag'])
        request.session[session_key] = True

    tab_count = tab_switch_event.tab_switch_count

    # Load exam questions from the JSON file
    try:
        with open(get_questions_file_path(), encoding='utf-8') as file:
            data = json.load(file)
        questions = data.get("questions", [])
    except FileNotFoundError:
        return HttpResponse("Error: Questions file not found!", status=404)
    except json.JSONDecodeError:
        return HttpResponse("Error: Failed to parse the questions file!", status=400)

    # Start background processing threads for video and audio monitoring
    global stop_event
    stop_event.clear()  # Reset the stop event flag
    threading.Thread(target=background_processing, args=(request,), daemon=True).start()
    threading.Thread(target=process_audio, args=(request,), daemon=True).start()

    # Render the exam template with questions and tab count
    return render(request, 'exam.html', {
        'questions': questions,
        'warning': warning,
        'tab_count': tab_count,
        'tab_switch_limit': TAB_SWITCH_LIMIT,
    })

# Submit exam
@login_required
def submit_exam(request):
    if request.method == 'POST':
        # Stop the background threads
        global stop_event
        stop_event.set()
        user = request.user

        # Load questions from ai.json
        try:
            with open(get_questions_file_path(), encoding='utf-8') as file:
                data = json.load(file)
        except FileNotFoundError:
            return HttpResponse("Error: Questions file not found!", status=404)
        except json.JSONDecodeError:
            return HttpResponse("Error: Failed to parse the questions file!", status=400)

        questions = data.get('questions', [])
        total_questions = len(questions)
        correct_answers = 0

        # Check answers
        for question in questions:
            question_id = question['id']
            user_answer = request.POST.get(f'answer_{question_id}')
            if user_answer == question['correct_answer']:
                correct_answers += 1

        # Save exam result
        exam = Exam(
            student=user.student,
            total_questions=total_questions,
            correct_answers=correct_answers,
            timestamp=timezone.now()
        )
        exam.save()

        request.session.pop(get_tab_switch_session_key(user.student.id), None)

        # Redirect to success page
        messages.success(request, 'You have successfully completed the exam!')
        return redirect('exam_submission_success')

    return HttpResponse("Invalid request method.", status=400)

# Tab switch tracking
stop_event = threading.Event()


# Set up logging
logger = logging.getLogger(__name__)

# Tab switch tracking View
@login_required
def record_tab_switch(request):
    if request.method == "POST":
        # Get the current student
        student = request.user.student
        logger.info(f"Student: {student}")

        # # Get the active exam for the student
        # active_exam = Exam.objects.filter(student=student, status='ongoing').first()
        # if not active_exam:
        #     logger.error("No active exam found for the student")
        #     return JsonResponse({"error": "No active exam found for the student"}, status=400)

        # logger.info(f"Active Exam: {active_exam}")

        # Get or create a CheatingEvent for the student and exam
        cheating_event, created = CheatingEvent.objects.get_or_create(
            student=student,
            event_type='tab_switch',  # Specify the event type
            defaults={
                'cheating_flag': False,
                'tab_switch_count': 0,
            }
        )

        logger.info(f"Cheating Event: {cheating_event}, Created: {created}")

        # Increment the tab switch count
        cheating_event.tab_switch_count += 1
        logger.info(f"Updated Tab Switch Count: {cheating_event.tab_switch_count}")

        # Set cheating_flag based on tab_switch_count
        cheating_event.cheating_flag = cheating_event.tab_switch_count >= 1
        logger.info(f"Cheating Flag: {cheating_event.cheating_flag}")

        # Save the updated CheatingEvent
        cheating_event.save()
        logger.info("Cheating Event saved successfully")

        # If tab switches reach the allowed limit, terminate the exam.
        if cheating_event.tab_switch_count >= TAB_SWITCH_LIMIT:
            stop_event.set()  # Stop background threads (ensure stop_event is defined)
            logger.info("Tab switch limit reached, terminated from the exam")
            return JsonResponse({
                "status": "terminated",
                "count": cheating_event.tab_switch_count,
                "auto_submit": True,
                "message": "You have exceeded the allowed tab switches. Your exam is terminated."
            }, status=200)
        # Return a JSON response with the updated count and flag
        return JsonResponse({
            "status": "updated",
            "count": cheating_event.tab_switch_count,
            "auto_submit": False,
            "cheating_flag": cheating_event.cheating_flag,
            "message": f"Tab switch detected! Total switches: {cheating_event.tab_switch_count}"
        }, status=200)

    return JsonResponse({"error": "Invalid request"}, status=400)


# Exam submission success page
def exam_submission_success(request):
    return render(request, 'exam_submission_success.html')

# Result page
@login_required
def result(request):
    user = request.user
    try:
        exam = Exam.objects.filter(student=user.student).latest('timestamp')
    except Exam.DoesNotExist:
        return HttpResponse("No exam found for this user", status=404)

    total_questions = exam.total_questions
    correct_answers = exam.correct_answers
    percentage = (correct_answers / total_questions) * 100

    context = {
        'user_name': user.username,
        'score': correct_answers,
        'total_questions': total_questions,
        'percentage': round(percentage, 2),
    }

    return render(request, 'result.html', context)



from django.http import JsonResponse

# Fetch warnings
@csrf_exempt
def get_warning(request):
    """Fetch real-time warnings for the exam page."""
    global warning
    return JsonResponse({'warning': warning})

# Streaming notifications to the proctor
def proctor_notifications(request):
    """Stream real-time cheating events to the proctor."""
    def event_stream():
        while True:
            events = CheatingEvent.objects.filter(cheating_flag=True).order_by('-timestamp')[:5]
            if events:
                yield f"data: {json.dumps([str(event) for event in events])}\n\n"
            time.sleep(5)
    
    return StreamingHttpResponse(event_stream(), content_type='text/event-stream')


## Logout
def logout(request):
    return render(request,'home.html')

# ----------------------Admin Plus Report Page ---------------------------------------

# Admin views
from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Sum
from django.contrib.admin.views.decorators import staff_member_required
from .models import Student, Exam, CheatingEvent, CheatingImage, CheatingAudio
@staff_member_required(login_url='/admin/login/')
def admin_dashboard(request):
    # Fetch students with counts for exams and cheating events
    students = Student.objects.annotate(
        exam_count=Count('exams'),
        cheating_event_count=Count('cheating_events')
    ).prefetch_related('exams', 'cheating_events')
    
    # Calculate trust score and exam scores for each student
    for student in students:
        # Example: Trust score decreases 10 points per cheating event (with a floor of 0)
        student.trust_score = max(0, 100 - (student.cheating_event_count * 10))
        
        for exam in student.exams.all():
            if exam.total_questions and exam.total_questions > 0 and exam.percentage_score is None:
                exam.percentage_score = calculate_exam_score(exam)
                exam.save()
    
    context = {
        'students': students,
    }
    return render(request, 'admin_dashboard.html', context)

## exam score
def calculate_exam_score(exam):
    """Calculate the exam score as a percentage."""
    if exam.total_questions and exam.total_questions > 0:
        return round((exam.correct_answers / exam.total_questions) * 100, 2)
    return 0.0


## Helper Function for aggregated detected objects
import json
def get_detected_objects_string(cheating_events):
    """Aggregate and convert the detected objects from all events into a list."""
    detected_objects_set = set()
    for event in cheating_events:
        # If detected_objects is not already a list, try converting it.
        objs = event.detected_objects
        if isinstance(objs, str):
            try:
                objs = json.loads(objs)
            except json.JSONDecodeError:
                objs = []
        # Now, objs should be a list so add each one to our set.
        if isinstance(objs, list):
            detected_objects_set.update(objs)
    return list(detected_objects_set)

### Report view
def report_page(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    exam = student.exams.first()  # Or however you want to choose the exam
    cheating_events = CheatingEvent.objects.filter(student=student)

    # Aggregate detected objects as a list
    detected_objects_list = get_detected_objects_string(cheating_events)
    detected_objects_str = ", ".join(detected_objects_list) if detected_objects_list else "No objects detected"

    # Sum up tab switch count from events
    total_tab_switch_count = cheating_events.aggregate(total=Sum('tab_switch_count'))['total'] or 0

    # Audio files: if you're using a FileField, Django automatically converts the stored file path
    # into a URL via the `.url` attribute once media is configured correctly.
    cheating_audios = CheatingAudio.objects.filter(event__student=student)
    audio_urls = [audio.audio.url for audio in cheating_audios if audio.audio]

    context = {
        'student': student,
        'exam': exam,
        'detected_objects': detected_objects_str,
        'total_tab_switch_count': total_tab_switch_count,
        # You can also add correct answer attempt and total questions:
        'correct_answers': exam.correct_answers,
        'total_questions': exam.total_questions,
        'cheating_status': any(
            event.event_type in ['object_detected', 'multiple_faces_detected', 'tab_switch']
            for event in cheating_events
        ),
        'cheating_images': [
            {
                'url': img.image.url,
                'event_type': img.event.event_type,
                'timestamp': img.timestamp
            }
            for img in CheatingImage.objects.filter(event__student=student)
        ],
        'audio_urls': audio_urls,
        'cheating_events': cheating_events,  # if you need to list them
    }
    return render(request, 'report_page.html', context)




from django.template.loader import get_template
from xhtml2pdf import pisa
# (Ensure you import any helper functions you might have, e.g., get_detected_objects_string)

def download_report(request, student_id):
    # Retrieve student and related data
    student = get_object_or_404(Student, id=student_id)
    exam = student.exams.first()  # Adjust as necessary
    cheating_events = CheatingEvent.objects.filter(student=student)
    
    # Process detected objects (assuming you have a helper function)
    detected_objects_list = get_detected_objects_string(cheating_events)
    detected_objects_str = ", ".join(detected_objects_list) if detected_objects_list else "No objects detected"

    # Sum up tab switch counts
    total_tab_switch_count = cheating_events.aggregate(total=Sum('tab_switch_count'))['total'] or 0

    # Audio URLs (xhtml2pdf might need absolute paths for images and other media,
    # but for simple cases it often works fine)
    cheating_audios = CheatingAudio.objects.filter(event__student=student)
    audio_urls = [audio.audio.url for audio in cheating_audios if audio.audio]

    # Prepare context for the template
    context = {
        'student': student,
        'exam': exam,
        'detected_objects': detected_objects_str,
        'total_tab_switch_count': total_tab_switch_count,
        'correct_answers': exam.correct_answers,
        'total_questions': exam.total_questions,
        'cheating_status': any(
            event.event_type in ['object_detected', 'multiple_faces_detected', 'tab_switch']
            for event in cheating_events
        ),
        'cheating_images': [
            {
                'url': img.image.url,
                'event_type': img.event.event_type,
                'timestamp': img.timestamp
            }
            for img in CheatingImage.objects.filter(event__student=student)
        ],
        'audio_urls': audio_urls,
        'cheating_events': cheating_events,
    }
    
    # Render the HTML template with context
    template = get_template('report_page.html')
    html = template.render(context)

    # Create a HttpResponse with PDF headers
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="report_{student.id}.pdf"'
    
    # Create PDF using xhtml2pdf (pisa)
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    # Check for errors
    if pisa_status.err:
        return HttpResponse('We had some errors while generating the PDF', status=500)
    
    return response


def add_question(request):
    return render(request, 'add_question.html')  # Ensure you have this template
