import py_audio2face as pya2f
a2f = pya2f.Audio2Face()

import os
from py_audio2face.settings import ROOT_DIR
##input = "D:/Github/py_audio2face/py_audio2face/assets/IS01_RF_01.wav";
a2f.set_emotion(anger=1.0, disgust=0.5, fear=0.1, sadness=0.2, update_settings=True)

a2f.audio2face_single(
    audio_file_path="D:/Github/py_audio2face/py_audio2face/assets/voice_male_p3_neutral_441_float.wav",
    output_path="D:/Github/py_audio2face/py_audio2face/assets/output/test.usd",
    fps=60,
    emotion_auto_detect=True
)