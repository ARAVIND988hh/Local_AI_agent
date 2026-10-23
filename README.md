 Local AI Agent (Jarvis)
_____________________________________________________________________________________

A local voice assistant for Windows with an animated desktop robot pet.

Runs on Ollama, so AI answers stay on your machine.



# Features
_____________________________________

  * Robot pet at the bottom-right of the screen. Hover over it to wake it up.

  * Wake word: say "Jarvis" followed by a command.

  * Open any installed app, search Google, play on YouTube.

  * Timers, notes, screenshots, volume control.

  * Keyboard and mouse control by voice (type, press keys, click buttons by name).

  * Ask questions about your screen using a local vision model.



# Requirements
__________________________________________

  * Windows 10/11

  * Python 3.12

  * \[Ollama](https://ollama.com/download)



# Setup
________________________

ollama pull qwen2.5:3b

ollama pull qwen2.5vl:3b

python -m venv venv

venv\\Scripts\\activate

pip install -r requirements.txt

python jarvis.py
________________

Set `MIC\_INDEX` at the top of `jarvis.py` to your microphone number

(`python -c "import sounddevice as sd; print(sd.query\_devices())"`).



# Example commands
________________________________________________
  * "Jarvis open Chrome"

  * "Jarvis search Python tutorial"

  * "Jarvis timer 5 minutes"

  * "Jarvis type hello world"

  * "Jarvis what is on my screen"



# Privacy

Speech recognition uses Google's free web API, so your voice is sent to Google.

Screen analysis and AI answers run locally through Ollama.

