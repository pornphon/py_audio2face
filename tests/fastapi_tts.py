#http://127.0.0.1:8000/tts/?text=Use%20the%20NVIDIA%20Audio2Face%20headless%20server%20and%20interact%20with%20it%20through%20a%20requests%20API
#http://192.168.1.216:8000/tts/?text=Use%20the%20NVIDIA%20Audio2Face%20headless%20server%20and%20interact%20with%20it%20through%20a%20requests%20API
#ส่งเสียงผ่าน AZure TTS ไปยัง NVIDIA Audio2Face ผ่าน gRPC Streaming
#เปิด audio2face แบบ gui ไว้เพื่อดูว่าโปรแกรทำอะไรอยู่ แล้วโหลด lib\site-packages\py_audio2face\assets\mark_arkit_solved_streaming.usd

# uvicorn fastapi_tts:app --reload --app-dir tests
# uvicorn fastapi_tts:app --reload --host 192.168.1.216 --port 8000 --app-dir tests


from fastapi import FastAPI, HTTPException
from test_stream_from_azure import tts_to_a2f
from pydantic import BaseModel


app = FastAPI()

@app.get("/tts/")
async def tts(text: str):
    """
    เรียกผ่าน GET /tts/?text=ข้อความที่ต้องการพูด
    จะส่งข้อความไปให้ tts_azure_gen สังเคราะห์เสียงออกลำโพง
    """
    if not text:
        raise HTTPException(status_code=400, detail="กรุณาระบุพารามิเตอร์ text")
    # เรียกฟังก์ชันสังเคราะห์เสียง (เล่นออกลำโพง)
    tts_to_a2f(text)
    return {"message": f"TTS for \"{text}\" has been started"}

@app.get("/")
async def read_root():
    return {"still ok!"}

class Item(BaseModel):
    text: str
    emotion: str = "neutral"  # Default emotion can be set to 'neutral' or any other valid emotion

# POST endpoint
@app.post("/speak/")
async def create_item(item: Item):
    print("Received POST request with item:", item)

    if not item.text:
        raise HTTPException(status_code=400, detail="กรุณาระบุพารามิเตอร์ text")
    tts_to_a2f(item.text)

    return {"message": f"TTS for \"{item.text}\" has been started"}