import speech_recognition as sr

for i in [1, 6, 12, 20]:
    try:
        with sr.Microphone(device_index=i) as src:
            print(i, "WORKS")
    except Exception as e:
        print(i, "fails:", e)