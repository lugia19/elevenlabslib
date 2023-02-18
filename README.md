# elevenlabslib
Full python implementation of the elevenlabs API.

# Installation

Just run `pip install elevenlabslib`, it's on pypi.

# Usage

Here is a very simple usage sample. 
- Retrieves a voice based on the name
- Plays back (using pydub) all its samples (and the preview) 
- Generates and plays back a new audio
- Deletes the newly created audio from the user history

```py
from elevenlabslib import *
import pydub
import pydub.playback
import io

#Playback function
def play(bytesData):
    sound = pydub.AudioSegment.from_file_using_temporary_files(io.BytesIO(bytesData))
    pydub.playback.play(sound)
    return

user = ElevenLabsUser("[API_KEY]")
voice = user.get_voices_by_name("Rachel")[0]  #This is a list because multiple voices can have the same name

play(voice.get_preview_bytes())

for sample in voice.get_samples():
    play(sample.get_audio_bytes())
    
play(voice.generate_audio_bytes("Test."))

for historyItem in user.get_history_items():
    if historyItem.text == "Test.":
        #The first items are the newest, so we can stop as soon as we find one.
        historyItem.delete()
        break
```

For a far more comprehensive example, check `example.py` on the github repo.
