import pyaudio
import wave
import numpy as np
import time
from threading import Thread

# Parameters
THRESHOLD = 2000  # Adjust based on environment
CHUNK = 2048  # Larger chunk size for smoother audio
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000  # High-quality audio
SOUND_END_DELAY = 4  # Time in seconds to stop recording after sound ends

# Initialize the audio system
p = pyaudio.PyAudio()
stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK)

def record_segment(frames):
    """Converts audio frames to bytes."""
    return b''.join(frames)

def audio_detection():
    """Detects speaking and returns audio segments during speaking."""
    print("Monitoring for speech during the exam...")
    sound_detected = False
    last_sound_time = 0
    frames = []

    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)

            # Check if the audio exceeds the threshold
            if np.max(np.abs(audio_data)) > THRESHOLD:
                if not sound_detected:
                    print("Speaking detected, starting recording...")
                    sound_detected = True
                last_sound_time = time.time()

                # Collect audio frames for this segment
                frames.append(data)

            # If sound stops for SOUND_END_DELAY, return the recording
            if sound_detected and (time.time() - last_sound_time > SOUND_END_DELAY):
                print("Speaking stopped, returning recording...")
                audio_bytes = record_segment(frames)  # Get audio data as bytes
                frames = []  # Reset frames for the next segment
                sound_detected = False
                return {
                    "audio_detected": True,
                    "audio_data": audio_bytes
                }

        except KeyboardInterrupt:
            break

    print("Stopping audio detection...")
    stream.stop_stream()
    stream.close()
    p.terminate()
    return {
        "audio_detected": False,
        "audio_data": None
    }