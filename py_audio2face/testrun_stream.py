import py_audio2face as pya2f
from media_toolkit import AudioFile


a2f = pya2f.Audio2Face()

import os
from py_audio2face.settings import ROOT_DIR
##input = "D:/Github/py_audio2face/py_audio2face/assets/IS01_RF_01.wav";
##a2f.set_emotion(anger=1.0, disgust=0.5, fear=0.1, sadness=0.2, update_settings=True)



my_audio=AudioFile().from_file("D:/Github/py_audio2face/py_audio2face/assets/IS01_RF_01.wav")
#my_audio=AudioFile().from_file("D:/Github/py_audio2face/py_audio2face/assets/voice_male_p3_neutral_441_float.wav")
audio_stream = my_audio.to_stream()
#a2f.set_emotion(anger=1.0, disgust=0.5, fear=0.1, sadness=0.2, update_settings=True)
a2f.stream_audio(audio_stream=audio_stream, samplerate=44100)

