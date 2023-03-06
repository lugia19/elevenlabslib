# elevenlabslib
Python wrapper for the full elevenlabs API.

# Installation

Just run `pip install elevenlabslib`, it's on [pypi](https://pypi.org/project/elevenlabslib/).

Note: On Linux, you may need to install portaudio. On debian and derivatives, it's `sudo apt-get install libportaudio2`, and possibly also `sudo apt-get install python3-pyaudio`.

# Usage

### **For a far more comprehensive example, check [example.py](https://github.com/lugia19/elevenlabslib/blob/master/example.py).**

Here is a very simple usage sample. 
- Retrieves a voice based on the name
- Plays back (using the included playback functions that use sounddevice) all its samples (and the preview) 
- Generates and plays back a new audio
- Deletes the newly created audio from the user history

```py
from elevenlabslib import *

user = ElevenLabsUser("API_KEY")
voice = user.get_voices_by_name("Rachel")[0]  # This is a list because multiple voices can have the same name

voice.play_preview(playInBackground=False)

voice.generate_and_play_audio("Test.", playInBackground=False)

for historyItem in user.get_history_items():
    if historyItem.text == "Test.":
        # The first items are the newest, so we can stop as soon as we find one.
        historyItem.delete()
        break
```
