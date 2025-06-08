import queue
import threading
import azure.cognitiveservices.speech as speechsdk
import py_audio2face as pya2f
from dotenv import load_dotenv
import os

load_dotenv(override=True)
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")
DEFAULT_VOICE_NAME = os.getenv("AZURE_SPEECH_VOICE_NAME")

audio_q = queue.Queue()
a2f = pya2f.Audio2Face()




# Callback class สำหรับ Azure PushAudioOutputStream
class AzureToQueueCallback(speechsdk.audio.PushAudioOutputStreamCallback):
    def write(self, audio_buffer):
        audio_q.put(bytes(audio_buffer))
        return len(audio_buffer)
    def close(self):
        audio_q.put(None)

# Generator สำหรับ feed เข้า a2f.stream_audio
def audio_stream_generator(blocksize=2048):
    buffer = b''
    while True:
        chunk = audio_q.get()
        if chunk is None:
            break
        buffer += chunk
        while len(buffer) >= blocksize:
            # ให้หาร 2 ลงตัว (16bit PCM)
            outsize = (blocksize // 2) * 2
            out = buffer[:outsize]
            buffer = buffer[outsize:]
            print(f"Yield chunk: {len(out)} bytes")
            yield out
    # chunk สุดท้าย
    if len(buffer) > 0:
        outsize = (len(buffer) // 2) * 2
        if outsize > 0:
            yield buffer[:outsize]

# ฟังก์ชันหลัก: สั่ง TTS แล้วส่งเข้า a2f.stream_audio
def stream_azure_tts_to_a2f(text, samplerate=44100):
    # 1. Setup Azure Speech
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SERVICE_REGION
    )
    speech_config.set_speech_synthesis_output_format(
        # speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        speechsdk.SpeechSynthesisOutputFormat.Riff44100Hz16BitMonoPcm
    )
    push_audio_stream = speechsdk.audio.PushAudioOutputStream(AzureToQueueCallback())
    audio_output_config = speechsdk.audio.AudioOutputConfig(stream=push_audio_stream)
    synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output_config)

    # 2. Run a2f.stream_audio ใน thread
    thread = threading.Thread(
        target=lambda: a2f.stream_audio(
            audio_stream=audio_stream_generator(),
            samplerate=samplerate
        )
    )
    thread.start()

    # 3. สั่ง TTS (chunk จะถูก feed เข้า audio_q และส่งไปที่ a2f)
    result = synth.speak_text_async(text).get()

    # 4. รอให้เล่นจบ
    thread.join()

# **เรียกใช้งาน**
stream_azure_tts_to_a2f("Hello Audio2Face", samplerate=44100)