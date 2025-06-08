import queue
import threading
import os
import numpy as np

# --- Imports จาก Library ที่จำเป็น ---
# สำหรับ Azure
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

# สำหรับ gRPC Streaming ของ Audio2Face
import grpc
# modules เหล่านี้จะถูกติดตั้งมาพร้อมกับ py_audio2face[streaming]
from py_audio2face.modules.clients.grpc_stub import audio2face_pb2, audio2face_pb2_grpc


# --- 1. Setup และ Configuration ---
load_dotenv(override=True)
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")

# ค่า gRPC Mappings สำหรับ Audio2Face (ปกติไม่ต้องเปลี่ยน)
A2F_GRPC_PORT = 50051
# ตรวจสอบให้แน่ใจว่า Path นี้ถูกต้องตรงกับในโปรแกรม Audio2Face ของคุณ
A2F_INSTANCE_NAME = "/World/audio2face/PlayerStreaming"


# Queue กลางสำหรับเป็นสะพานเชื่อมระหว่าง Azure และ gRPC
audio_q = queue.Queue()


# --- 2. Producer: ส่วนของ Azure TTS (เหมือนเดิม) ---

class AzureToQueueCallback(speechsdk.audio.PushAudioOutputStreamCallback):
    """Callback ที่รับข้อมูลเสียงจาก Azure แล้วส่งเข้า Queue"""
    def write(self, audio_buffer: memoryview):
        audio_q.put(bytes(audio_buffer))
        return len(audio_buffer)

    def close(self):
        audio_q.put(None) # ส่งสัญญาณ None บอกว่าเสียงจบแล้ว

def start_azure_tts_synthesis(text: str, samplerate: int, voice_name: str):
    """
    ฟังก์ชันสำหรับเริ่มการสังเคราะห์เสียงจาก Azure ใน Thread แยก
    ข้อมูลเสียงจะถูกส่งเข้า audio_q อย่างต่อเนื่อง
    """
    print(f"Azure: Starting synthesis for text: '{text}'")
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SERVICE_REGION)
    
    format_map = {
        16000: speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
        24000: speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
        48000: speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm,
    }
    output_format = format_map.get(samplerate)
    if not output_format:
        raise ValueError(f"Unsupported samplerate for Azure Raw PCM: {samplerate}")

    speech_config.set_speech_synthesis_output_format(output_format)
    speech_config.speech_synthesis_voice_name = voice_name

    push_stream = speechsdk.audio.PushAudioOutputStream(AzureToQueueCallback())
    audio_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)
    
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    
    result = synthesizer.speak_text_async(text).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"Azure TTS Error: {result.reason}")
        audio_q.put(None)


# --- 3. Consumer: ส่วนของ gRPC Streamer ไปยัง A2F (แก้ไขแล้ว) ---

def stream_audio_to_a2f_via_grpc(
    samplerate: int,
    instance_name: str = A2F_INSTANCE_NAME,
    grpc_port: int = A2F_GRPC_PORT
):
    """
    สร้าง gRPC connection และ stream ข้อมูลจาก audio_q ไปยัง Audio2Face
    """
    print(f"gRPC: Connecting to Audio2Face on localhost:{grpc_port}")
    url = f"localhost:{grpc_port}"

    with grpc.insecure_channel(url) as channel:
        stub = audio2face_pb2_grpc.Audio2FaceStub(channel)

        def request_generator():
            # 1. ส่ง Start Marker ก่อนเสมอ
            print("gRPC: Sending Start Marker...")
            start_marker = audio2face_pb2.PushAudioRequestStart(
                samplerate=samplerate,
                instance_name=instance_name,
                block_until_playback_is_finished=True
            )
            yield audio2face_pb2.PushAudioStreamRequest(start_marker=start_marker)

            # 2. วนลูปเพื่อดึงข้อมูลเสียงจาก Queue แล้วส่งไป
            print("gRPC: Start streaming audio chunks from queue...")
            while True:
                chunk = audio_q.get()
                if chunk is None:
                    print("gRPC: End of stream signal received.")
                    break
                
                # --- [ โค้ดที่เพิ่มเข้ามาเพื่อแก้ไขปัญหา NaN ] ---
                # แปลง chunk (bytes) เป็น numpy array ของตัวเลข 16-bit
                audio_samples = np.frombuffer(chunk, dtype=np.int16)
                
                # ตรวจสอบว่าทุก sample ใน chunk เป็น 0 (เงียบสนิท) หรือไม่
                if np.all(audio_samples == 0):
                    print("gRPC: Skipping silent chunk to prevent NaN error.")
                    continue # ข้ามการส่ง chunk นี้ไป แล้วไปดึง chunk ใหม่
                # --- [ จบส่วนที่เพิ่มเข้ามา ] ---
                
                # ถ้า chunk ไม่ได้เงียบสนิท ก็ส่งข้อมูลเสียงไปตามปกติ
                yield audio2face_pb2.PushAudioStreamRequest(audio_data=chunk)
        
        # เริ่มการส่ง stream
        response = stub.PushAudioStream(request_generator())
        
        if response.success:
            print(f"gRPC: Stream successfully sent to {instance_name}.")
        else:
            print(f"gRPC: Stream failed. Message: {response.message}")
        return response.success


# --- 4. Main Execution (เหมือนเดิม) ---
if __name__ == "__main__":
    # แนะนำให้ใช้ข้อความยาวๆ ที่มีการเว้นวรรคปกติ
    TEXT_TO_SPEAK = "This is a much more robust implementation that actively filters out silent audio chunks before sending them to Audio2Face."
    
    # ลองสลับ Voice เพื่อทดสอบได้
    VOICE = "en-US-JennyNeural" # "th-TH-AcharaNeural"
    SAMPLE_RATE = 48000

    tts_thread = threading.Thread(
        target=start_azure_tts_synthesis,
        args=(TEXT_TO_SPEAK, SAMPLE_RATE, VOICE)
    )
    tts_thread.start()

    try:
        stream_audio_to_a2f_via_grpc(samplerate=SAMPLE_RATE)
    except grpc.RpcError as e:
        print(f"\nAn gRPC error occurred: {e.details()}")
        print("Please ensure Audio2Face application is running and the gRPC service is enabled.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    tts_thread.join()
    print("\nProgram finished.")