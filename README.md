# elevenlabslib
![PyPI - Downloads](https://img.shields.io/pypi/dm/elevenlabslib?color=%23009FFFFF&style=for-the-badge)
![PyPI](https://img.shields.io/pypi/v/elevenlabslib?color=%23FE6137&style=for-the-badge)
![GitHub last commit](https://img.shields.io/github/last-commit/lugia19/elevenlabslib?style=for-the-badge)

Python wrapper for the full elevenlabs API.

# Installation

Just run `pip install elevenlabslib`, it's on [pypi](https://pypi.org/project/elevenlabslib/).

Note: On Linux, you may need to install portaudio. On debian and derivatives, it's `sudo apt-get install libportaudio2`, and possibly also `sudo apt-get install python3-pyaudio`.

**IMPORTANT**: The library requires libsndfile `v1.1.0` or newer, as that is when mp3 support was introduced. This won't be an issue on Windows, but may be relevant on other platforms. Check the [soundfile](https://github.com/bastibe/python-soundfile#installation) repo for more information.

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
