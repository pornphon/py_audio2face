#ส่งเสียงผ่าน AZure TTS ไปยัง NVIDIA Audio2Face ผ่าน gRPC Streaming
#เปิด audio2face แบบ gui ไว้เพื่อดูว่าโปรแกรทำอะไรอยู่ แล้วโหลด lib\site-packages\py_audio2face\assets\mark_arkit_solved_streaming.usd

import queue
import threading
import os
import numpy as np
import time
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
import importlib_resources

# สำหรับ gRPC Streaming ของ Audio2Face
import grpc
from py_audio2face.modules.clients.grpc_stub import audio2face_pb2, audio2face_pb2_grpc
import py_audio2face as pya2f


# --- 1. Setup และ Configuration ---
load_dotenv(override=True)
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")

#load audio2face + defaults file
# a2f = pya2f.Audio2Face()
# mark_usd_file= importlib_resources.files('py_audio2face') / 'assets' / 'mark_arkit_solved_streaming.usd'
# a2f.start_headless_server()
# if a2f.loaded_scene != mark_usd_file:
#     a2f.load_scene(mark_usd_file)



# ค่า gRPC Mappings สำหรับ Audio2Face (ปกติไม่ต้องเปลี่ยน)
A2F_GRPC_PORT = 50051
# ตรวจสอบให้แน่ใจว่า Path นี้ถูกต้องตรงกับในโปรแกรม Audio2Face ของคุณ ชื่อตัวละคร
A2F_INSTANCE_NAME = "/World/audio2face/PlayerStreaming"

# Queue กลางสำหรับเป็นสะพานเชื่อมระหว่าง Azure และ gRPC
audio_q = queue.Queue()

# --- 2. Producer: ส่วนของ Azure TTS (เหมือนเดิม) ---
class AzureToQueueCallback(speechsdk.audio.PushAudioOutputStreamCallback):
    """Callback ที่รับข้อมูลเสียงจาก Azure แล้วส่งเข้า Queue"""
    def write(self, audio_buffer: memoryview):
        chunk_size = len(audio_buffer)
        print(f"  [Azure Callback] -> write() called, got {chunk_size} bytes. Putting into queue...")
        audio_q.put(bytes(audio_buffer))
        return len(audio_buffer)

    def close(self):
        print("  [Azure Callback] -> close() called. Putting 'None' into queue to signal end.")
        audio_q.put(None) # ส่งสัญญาณ None บอกว่าเสียงจบแล้ว

def start_azure_tts_synthesis(text: str, samplerate: int, voice_name: str):
    """
    ฟังก์ชันสำหรับเริ่มการสังเคราะห์เสียงจาก Azure ใน Thread แยก
    ข้อมูลเสียงจะถูกส่งเข้า audio_q อย่างต่อเนื่อง
    """
    try:
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
        print(f"Azure: tts Finished for text")
    finally:
        print("Azure Thread: Synthesis process finished. Putting 'None' into queue to guarantee termination.")
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

                # 1. แปลง bytes เป็น int16 array เพื่อเช็คความเงียบ (เหมือนเดิม)
                audio_samples_int16 = np.frombuffer(chunk, dtype=np.int16)

                # 2. เช็คความเงียบ (เหมือนเดิม)
                if np.all(audio_samples_int16 == 0):
                    print("gRPC: Skipping silent chunk to prevent NaN error.")
                    continue
                    
                # --- ส่วนที่แก้ไข ---
                # 3. แปลง int16 array เป็น float32 array และทำ Normalization
                #    (ค่า int16 อยู่ระหว่าง -32768 ถึง 32767, เราจึงหารด้วย 32768.0 เพื่อให้อยู่ในช่วง -1.0 ถึง 1.0)
                audio_samples_float32 = (audio_samples_int16.astype(np.float32) / 32768.0)*2
                audio_samples_float32 = np.clip(audio_samples_float32, -1.0, 1.0)  # ป้องกันค่าเกินช่วง
                
                # 4. แปลง float32 array กลับไปเป็น bytes
                new_chunk_bytes = audio_samples_float32.tobytes()
                # --- จบส่วนที่แก้ไข ---
                
                # 5. ส่ง chunk ที่เป็น bytes (ของ float32) ไปแทน
                yield audio2face_pb2.PushAudioStreamRequest(audio_data=new_chunk_bytes)


        # เริ่มการส่ง stream
        response = stub.PushAudioStream(request_generator())
        
        if response.success:
            print(f"gRPC: Stream successfully sent to {instance_name}.")
        else:
            print(f"gRPC: Stream failed. Message: {response.message}")
        return response.success





def tts_to_a2f(text2speak: str, samplerate: int = 48000, voice_name: str = "th-TH-AcharaNeural"):
    """
    ฟังก์ชันหลักสำหรับเริ่มการสังเคราะห์เสียงจาก Azure และส่งไปยัง Audio2Face
    """
    print(f"Starting TTS synthesis for text: '{text2speak}'")
    
    tts_thread = threading.Thread(
        target=start_azure_tts_synthesis,
        args=(text2speak, samplerate, voice_name)
    )
    tts_thread.start()

    try:
        stream_audio_to_a2f_via_grpc(samplerate=samplerate)
    except grpc.RpcError as e:
        print(f"\nAn gRPC error occurred: {e.details()}")
        print("Please ensure Audio2Face application is running and the gRPC service is enabled.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    tts_thread.join()
    print("\nProgram finished.")




# --- 4. Main Execution (เหมือนเดิม) ---
if __name__ == "__main__":
    # แนะนำให้ใช้ข้อความยาวๆ ที่มีการเว้นวรรคปกติ
    TEXT_TO_SPEAK = "This is a much more robust implementation that actively filters out silent audio chunks before sending them to Audio2Face."
    
    # VOICE = "en-US-JennyNeural"
    VOICE = "th-TH-NiwatNeural"
    #th-TH-PremwadeeNeural (Female)
    #th-TH-NiwatNeural (Male)
    #th-TH-AcharaNeural (Female)
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