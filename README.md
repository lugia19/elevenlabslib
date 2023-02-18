# elevenlabslib
Full python implementation of the elevenlabs API.

# Installation

Just run `pip install elevenlabslib` (once it's available on pypi, otherwise just clone the repo and install it that way).

# Usage

Here is a very simple usage sample to retrieve a voice based on the name, play back (using pydub) all its samples (and the preview) and then generate and play back a new audio.

```py
from elevenlabslib import *
import pydub

user = ElevenLabsUser("[API_KEY]")
voice = user.get_voices_by_name("Rachel")[0]  #This is a list because multiple voices can have the same name

play(voice.get_preview_bytes())

for sample in voice.get_samples():
    play(sample.get_audio_bytes())
    
voice.generate_audio_bytes("Test.")


def play(bytesData):
    sound = AudioSegment.from_file_using_temporary_files(io.BytesIO(bytesData))
    pydub.playback.play(sound)
    return
```

For a more complete example, check the `example.py` file.
