import queue
import threading
import azure.cognitiveservices.speech as speechsdk
import py_audio2face as pya2f
from dotenv import load_dotenv
import os

# --- 1. Setup ---
# โหลดค่าจากไฟล์ .env
load_dotenv(override=True)
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")
DEFAULT_VOICE_NAME = os.getenv("AZURE_SPEECH_VOICE_NAME", "th-TH-NiwatNeural") # ใส่เสียง default ที่ต้องการ

# สร้าง Queue กลางสำหรับพักข้อมูลเสียง
audio_q = queue.Queue()

# --- 2. เชื่อมต่อ Audio2Face ---
# แนะนำให้เชื่อมต่อก่อนเริ่มทำงาน เพื่อให้แน่ใจว่า A2F พร้อมใช้งาน
try:
    a2f = pya2f.Audio2Face() 
    print("Successfully connected to Audio2Face.")
except Exception as e:
    print(f"Failed to connect to Audio2Face: {e}")
    print("Please ensure NVIDIA Omniverse and Audio2Face are running.")
    exit()


# --- 3. Callback และ Generator (ส่วนนี้ถูกต้องอยู่แล้ว) ---

# Callback class สำหรับรับข้อมูลเสียงจาก Azure แล้วส่งเข้า Queue
class AzureToQueueCallback(speechsdk.audio.PushAudioOutputStreamCallback):
    def write(self, audio_buffer: memoryview):
        """Callback ที่ถูกเรียกเมื่อมีข้อมูลเสียงก้อนใหม่มาจาก Azure"""
        audio_q.put(bytes(audio_buffer))
        return len(audio_buffer)

    def close(self):
        """Callback ที่ถูกเรียกเมื่อ stream สิ้นสุด"""
        # ใส่ None เพื่อเป็นสัญญาณบอก consumer (generator) ว่าข้อมูลหมดแล้ว
        audio_q.put(None) 

# Generator สำหรับดึงข้อมูลเสียงจาก Queue เพื่อส่งให้ A2F
def audio_stream_generator(blocksize=2048):
    """
    ดึงข้อมูลเสียงจาก Queue มาทีละ chunk และ yield เพื่อให้ a2f.stream_audio นำไปใช้
    """
    buffer = b''
    while True:
        chunk = audio_q.get()
        if chunk is None: # เมื่อเจอ None แสดงว่าจบ stream
            break
        
        buffer += chunk
        while len(buffer) >= blocksize:
            # ตัดข้อมูลตามขนาด blocksize (ต้องหาร 2 ลงตัวสำหรับ 16-bit PCM)
            outsize = (blocksize // 2) * 2 
            out_chunk = buffer[:outsize]
            buffer = buffer[outsize:]
            yield out_chunk
            
    # ส่งข้อมูลส่วนที่เหลือสุดท้ายออกไป
    if len(buffer) > 0:
        outsize = (len(buffer) // 2) * 2
        if outsize > 0:
            yield buffer[:outsize]


# --- 4. ฟังก์ชันหลักที่แก้ไขแล้ว ---

def stream_azure_tts_to_a2f(text: str, samplerate: int = 48000, voice_name: str = DEFAULT_VOICE_NAME):
    """
    สั่งสังเคราะห์เสียงจาก Azure TTS และสตรีมไปยัง Audio2Face แบบ Real-time
    
    Args:
        text (str): ข้อความที่ต้องการแปลงเป็นเสียง
        samplerate (int): Sample rate ที่ต้องการ (แนะนำ 24000 หรือ 48000)
        voice_name (str): ชื่อเสียงของ Azure ที่ต้องการใช้
    """
    print("-" * 50)
    print(f"Streaming text with samplerate: {samplerate}Hz")
    
    # 1. Setup Azure Speech Config
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SERVICE_REGION
    )
    
    # **[การแก้ไขที่ 1] เลือกฟอร์แมตเสียงดิบ (Raw PCM) ที่ไม่มี Header**
    # และทำให้ฟอร์แมตสอดคล้องกับ samplerate ที่รับเข้ามา
    format_map = {
        16000: speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
        24000: speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
        48000: speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm,
    }
    
    output_format = format_map.get(samplerate)
    if not output_format:
        # แจ้งเตือนและยกเลิกถ้า samplerate ไม่รองรับ
        raise ValueError(f"Unsupported samplerate: {samplerate}. Supported values are {list(format_map.keys())}.")

    speech_config.set_speech_synthesis_output_format(output_format)
    speech_config.speech_synthesis_voice_name = voice_name

    # ตั้งค่า output ให้ไปที่ Callback Class ของเรา
    push_audio_stream = speechsdk.audio.PushAudioOutputStream(AzureToQueueCallback())
    audio_output_config = speechsdk.audio.AudioOutputConfig(stream=push_audio_stream)
    
    # สร้าง Synthesizer
    synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output_config)

    # 2. เริ่ม Thread สำหรับการสตรีมไปยัง Audio2Face (Consumer)
    # **[การแก้ไขที่ 2] ส่ง samplerate ที่ถูกต้องตรงกันไปยัง A2F**
    a2f_thread = threading.Thread(
        target=a2f.stream_audio,
        kwargs={
            'audio_stream': audio_stream_generator(),
            'samplerate': samplerate, # <--- ใช้ samplerate ที่ตรงกับเสียงที่สร้าง
            'instance_name': "/World/audio2face/Player" # ระบุ Player instance ที่ถูกต้องใน A2F
        }
    )
    a2f_thread.start()

    # 3. สั่งสังเคราะห์เสียงจาก Azure (Producer)
    # การเรียก .get() จะทำให้ฟังก์ชันนี้รอจนกว่า Azure จะส่งข้อมูลเสียงทั้งหมดเข้า Callback เสร็จ
    print(f"Synthesizing and streaming text: '{text}'")
    result = synth.speak_text_async(text).get()

    # ตรวจสอบผลลัพธ์การสังเคราะห์
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Azure TTS synthesis completed successfully.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Speech synthesis canceled: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Error details: {cancellation_details.error_details}")

    # 4. รอให้ Thread ของ A2F ทำงานจนจบ (เล่นเสียงที่ค้างใน Queue จนหมด)
    a2f_thread.join()
    print("Streaming to Audio2Face finished.")
    print("-" * 50)


# --- 5. การเรียกใช้งาน ---
if __name__ == "__main__":
    try:
        # ใช้ Sample Rate ที่ให้คุณภาพสูง และตรงกับที่ A2F ทำงานได้ดี (เช่น 48000 Hz)
        stream_azure_tts_to_a2f(
            "Hello Audio2Face, this is a real-time stream from Azure Cognitive Services.",
            samplerate=48000,
            voice_name="en-US-JennyNeural"
        )
        
        stream_azure_tts_to_a2f(
            "สวัสดีครับ ออดิโอทูเฟซ นี่คือการทดสอบสตรีมเสียงภาษาไทยแบบเรียลไทม์",
            samplerate=48000,
            voice_name="th-TH-NiwatNeural"
        )

    except ValueError as ve:
        print(f"Configuration Error: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")