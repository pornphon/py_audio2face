#ส่ง stream จาก azure ให้ audio2face




import queue
import os
from dotenv import load_dotenv
import threading
import azure.cognitiveservices.speech as speechsdk
from media_toolkit import AudioFile

load_dotenv(override=True)
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")
DEFAULT_VOICE_NAME = os.getenv("AZURE_SPEECH_VOICE_NAME")

audio_q = queue.Queue()

class AzureToQueueCallback(speechsdk.audio.PushAudioOutputStreamCallback):
    def write(self, audio_buffer):
        audio_q.put(bytes(audio_buffer))
        return len(audio_buffer)
    def close(self):
        # Signal to consumer to end
        audio_q.put(None)

push_audio_stream = speechsdk.audio.PushAudioOutputStream(AzureToQueueCallback())
audio_output_config = speechsdk.audio.AudioOutputConfig(stream=push_audio_stream)
speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SERVICE_REGION)
speech_config.set_speech_synthesis_output_format(
    speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
)
synth = speechsdk.SpeechSynthesizer(
    speech_config=speech_config,
    audio_config=audio_output_config
)

import py_audio2face as pya2f
a2f = pya2f.Audio2Face()

def stream_to_a2f(audio_q, a2f, sample_rate):
    def generator():
        while True:
            chunk = audio_q.get()
            if chunk is None:
                break

            print(f"Chunk {i}: {len(chunk)} bytes")
            i += 1
            yield chunk
    a2f.stream_audio(audio_stream=generator(), samplerate=sample_rate)

t = threading.Thread(target=stream_to_a2f, args=(audio_q, a2f, 48000))
t.start()

# สำคัญ: ใช้ .get() แทน .speak_text_async() เพื่อรอให้พูดจบ
result_future = synth.speak_text_async("ดี")
result = result_future.get()  # blocking รอจบ

# Callback จะใส่ None ลง queue เมื่อจบ audio
t.join()
