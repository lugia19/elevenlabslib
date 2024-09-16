# Usage examples

## Generate, play back, save and delete a generated audio

```python
from elevenlabslib import *
from elevenlabslib.helpers import play_audio_v2
user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]

# Generate the audio and get the bytes and historyID. 
# The GenerationOptions specified here only apply for this generation.
audio_future, generation_info_future = voice.generate_audio_v3("This is a test.", GenerationOptions(stability=0.4))
generation_info = generation_info_future.result()
audio_data = audio_future.result()
# Play it back
play_audio_v2(audio_data)

# Save it to disk, in ogg format (can be any format supported by SoundFile)
save_audio_v2(audio_data, "testAudio.ogg", outputFormat="ogg")

# Fetch the corresponding historyItem
historyItem = user.get_history_item(generation_info.history_item_id)

# Delete it
historyItem.delete()
```

## Speech to speech on a long file (eg, an audiobook)
```python
from elevenlabslib import *
from elevenlabslib.utils import sts_long_audio

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]
source_audio_file = open(r"C:\your\audio\file.mp3", "rb")

converted_audio = sts_long_audio(source_audio_file, voice)

save_audio_v2(converted_audio, r"C:\your\output\location.mp3", "mp3")
```

## Projects Listing and converting
```python
from elevenlabslib import *

user = User("YOUR_API_KEY")
projects = user.get_projects()
for project in projects:
    chapters = project.get_chapters()   #Get the project's chapters
    for chapter in chapters:
        print(chapter.name)
        chapter_snapshots = chapter.get_snapshots() #Get the chapter's snapshots (audio versions)
        if not chapter.conversion_progress and len(chapter_snapshots) == 0:
            print("Chapter has no snapshots and isn't being converted, converting...")
            chapter.convert()
```

## Speech to speech
```python
from elevenlabslib import *

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]

generation_options = GenerationOptions(model_id="eleven_english_sts_v2", stability=0.2)

source_audio_file = open(r"C:\your\audio\file.mp3", "rb")
#sorce_audio can also be bytes, to allow you to pass input from a microphone:
source_audio_bytes = source_audio_file.read()

voice.stream_audio_v3(source_audio_file, generation_options=generation_options)
voice.stream_audio_v3(source_audio_bytes, generation_options=generation_options)
```

## Search the voice library and add a voice to your account

```python
from elevenlabslib import *
from elevenlabslib.helpers import *

user = User("YOUR_API_KEY")
#Filter by the characteristics of the speaker
voice_filter = LibVoiceInfo(category=LibCategory.PROFESSIONAL, gender=LibGender.MALE, age=LibAge.YOUNG,
                            accent=LibAccent.AMERICAN, language="en")

#Get the 10th-15th voices fitting the above criteria (may be less than 5 if there aren't enough)
libvoices = user.search_voice_library(query_page_size=5, starting_page=2, advanced_filters=voice_filter)

print(libvoices[0].name)
#Add one of them to your account.
user.add_shared_voice(libvoices[0], "Test Add!")
```

## Apply effects to audio as it's being played back

```python
from elevenlabslib import *
import numpy

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]


#For this example, we turn up the gain by 5x.
def increase_gain(audio_chunk, sample_rate):
    return numpy.clip(audio_chunk * 5, -1.0, 1.0)


voice.stream_audio_v3("This audio will have its volume increased.",
                      playback_options=PlaybackOptions(audioPostProcessor=increase_gain))
```

## Use ReusableInputStreamer for lower latency websocket streaming

```python
import threading
from elevenlabslib import *
from elevenlabslib.utils import ReusableInputStreamer

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]

text = "This is simply a test text used for websockets."


def write():
    yield text


# ReusableInputStreamer takes care of keeping an active websocket connection, ensuring there is always one ready for use.
# This cuts down on the latency loss due to websockets, as the connection is already prepared beforehand.
input_streamer = ReusableInputStreamer(voice)
playback_done_event = threading.Event()
input_streamer.queue_audio(write())
input_streamer.queue_audio(write(),
                           playbackOptions=PlaybackOptions(runInBackground=True, onPlaybackEnd=playback_done_event.set))

#Wait for the second playback to end.
playback_done_event.wait()

# Has to be closed for the code to exit.
input_streamer.stop()
```

## Use prompting to add emotion

```python
from elevenlabslib import *

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]
#Low stability makes prompting more effective.
generation_options = GenerationOptions(stability=0.1)
prompting_options = StitchingOptions(next_text="she shouted angrily.")

#The spoken audio will only contain chosen text, and will cut out the pre/post prompt.
voice.stream_audio_v3("I've had enough!", generation_options=generation_options,
                               prompting_options=prompting_options)
```

## Advanced websocket features: Control amount of buffering and force flush on a specific chunk

```python
from elevenlabslib import *

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]

texts = ["This is a test audio for websockets.", "This is just meant to showcase how it works.", "Like this.",
         "This will behave the same as having an LLM generate text."]


def write():
    for text in texts:
        yield {"text": text, "try_trigger_generation": False, "flush": texts.index(text) == 2}


#This is the worst-case scenario for speed/latency, multilingual v2 with style enabled.
generation_options = GenerationOptions(model="eleven_multilingual_v2", style=0.2)

#The library takes care of setting these values by default, I'm only overwriting them here to show them.
websocket_options = WebsocketOptions(chunk_length_schedule=[125],
                                     try_trigger_generation=False)

#This will now work without stuttering, but it will add some extra latency before playback begins.
voice.stream_audio_v3(write(),
                               PlaybackOptions(runInBackground=False),
                               generation_options=generation_options,
                               websocket_options=websocket_options)
```

## Add and use a pronunciation dictionary

```python
from elevenlabslib import *

user = User("YOUR_API_KEY")
voice = user.get_available_voices()[0]

new_dictionary = user.add_pronunciation_dictionary("new_dictionary", "", "path_to_dictionary.pls")

voice.stream_audio_v3("This is a test. Both instances of test will be pronounced as tomato.",
                               playback_options=PlaybackOptions(runInBackground=False),
                               generation_options=GenerationOptions(model="eleven_monolingual_v1",
                                                                   pronunciation_dictionaries=[new_dictionary]))
```

## Generate audio in PCM format

```python
from elevenlabslib import *

api_key = "api_key"
user = User(api_key)
premadeVoice = user.get_voices_by_name_v2("Rachel")[0]

#pcm_highest (and mp3_highest) will automatically select the highest quality available to your account.
audioData = premadeVoice.generate_audio_v3("This is a test.", GenerationOptions(output_format="pcm_highest"))
```

## Use the Synthesizer utility class to manage playback

```python
from elevenlabslib import *
from elevenlabslib.utils import Synthesizer

api_key = "api_key"
user = User(api_key)
voice = user.get_available_voices()[0]

#The synthesizer will manage streaming all the audio and playing it back in order.
#The onPlaybackStart and onPlaybackEnd parameters set here will be run for every audio.
playbackOptions = PlaybackOptions(onPlaybackStart=lambda: print("Playback Start"),
                                  onPlaybackEnd=lambda: print("Playback End"))
synthesizer = Synthesizer(defaultPlaybackOptions=playbackOptions)
synthesizer.start()
for i in range(10):
    print(f"Loop {i}")
    if i != 6:
        synthesizer.add_to_queue(voice, f"This is test {i}.")
    else:
        #You can override both GenerationOptions and PlaybackOptions on any generation
        synthesizer.add_to_queue(voice, f"This is test {i}.", GenerationOptions(stability=0),
                                 PlaybackOptions(onPlaybackStart=lambda: print("Stability 0 Start"),
                                                 onPlaybackEnd=lambda: print("Stability 0 End")))

input("We're past the for loop already. Hit enter when you'd like to stop the playback.\n")
synthesizer.stop()

```

## Use input streaming with the OpenAI API
Adapted from [this example](https://gist.github.com/NN1985/a0712821269259061177c6abb08e8e0a) using the official wrapper.

```python
from elevenlabslib import *
import openai

client = openai.Client(api_key="your_openai_key_here")
#Using an AsyncClient is also supported - the library will handle the resulting async_generator.
user = User("your_elevenlabs_api_key")


def write(prompt: str):
    for chunk in client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
    ):
        # Extract the content from the chunk if available
        content = chunk.choices[0].delta.content
        finish_reason = chunk.choices[0].finish_reason
        if content:
            print(content)
            yield content
        if finish_reason is not None and finish_reason == 'stop':
            break


# Generate a text stream
text_stream = write("Give me a five sentence response.")

# Pick a voice
voice = user.get_available_voices()[0]

# Stream the audio
# Note: The last parameter will be None due to the API not giving websocket generations a historyID
audio_queue, transcript_queue, audio_stream_future, _ = voice.stream_audio_v3(
    text_stream, PlaybackOptions(runInBackground=False),
    GenerationOptions(latencyOptimizationLevel=4),
    WebsocketOptions(try_trigger_generation=True, chunk_length_schedule=[50])
)
```

## Control the background playback of an audio

```python
import time
from elevenlabslib import *
from elevenlabslib.helpers import play_audio_v2

voice = User("api_key").get_available_voices()[0]
usingStreaming = True

if usingStreaming:
    #The stream function uses a future rather than returing the audioStream directly.
    _, _, audioStreamFuture, _ = voice.stream_audio_v3("I am currently testing the playback control.",
                                                       PlaybackOptions(runInBackground=True))[1]
    audioStream = audioStreamFuture.result()
else:
    audio_data, _ = voice.generate_audio_v3("I am currently testing the playback control.")[
        1]
    audioStream = play_audio_v2(audio_data, PlaybackOptions(runInBackground=True))

#Wait for the thread to be active, then stop the playback.
while not audioStream.active:
    time.sleep(0.1)

audioStream.abort()
```

## Play back an audio on a specific output device

```python
from elevenlabslib import *
import sounddevice
import random

api_key = "api_key"
user = User(api_key)
voice = user.get_voices_by_name_v2("Rachel")[0]

#Get all available output devices
outputDevices = [device for device in sounddevice.query_devices() if device["max_output_channels"] > 0]

#Print them all to console
for device in outputDevices:
    print(f"Device id {device['index']}: {device['name']}")

#Choose one (randomly for this example) and use it.
outputDevice = random.choice(outputDevices)
print(f"Randomly chosen device: {outputDevice['name']}")

#WARNING: Since we're choosing it randomly, it may be invalid and cause errors.
voice.stream_audio_v3("Device output test.",
                               PlaybackOptions(runInBackground=False, portaudioDeviceID=outputDevice["index"]))
```

## Check if an audio file was generated with Elevenlabs

```python
from elevenlabslib.helpers import *

filePath = "audioFile.mp3"
audioBytes = open(filePath, "rb").read()

responseDict = run_ai_speech_classifier(audioBytes)
print(f"There's a {responseDict['probability'] * 100}% chance that this audio was AI generated.")
```

## Create and edit a cloned voice

```python
from elevenlabslib import *

api_key = "api_key"
newVoiceName = "newVoice"
user = User(api_key)

try:
    existingVoice = user.get_voices_by_name_v2(newVoiceName)[0]
except IndexError:
    print("Voice doesn't exist, let's create it")
    if not user.get_voice_clone_available():
        print("Sorry, your subscription doesn't allow you to use voice cloning.")
    else:
        #Load a sample from a filepath and use it to create the new voice.
        firstSample = r"X:\sample1.mp3"
        newClonedVoice = user.clone_voice_by_path(newVoiceName, firstSample)
        print("New voice:")
        print(newClonedVoice.name)

        #Add a sample by loading it as bytes.
        secondSample = open(r"X:\sample2.mp3", "rb").read()
        newClonedVoice.add_samples_bytes({
            "sample2.mp3": secondSample
        })
```

## Create a voice using Voice Design

```python
from elevenlabslib.helpers import *
from elevenlabslib import *

api_key = "api_key"
newVoiceName = "newVoice"
user = User(api_key)

try:
    #Generate the audio and get the temporary voiceID.
    temporaryVoiceID, generatedAudio = user.design_voice(gender="female", accent="american", age="young",
                                                         accent_strength=1.0)

    #Play back the generated audio.
    play_audio_v2(generatedAudio, PlaybackOptions(runInBackground=False))

    #Add the voice to the account.
    newGeneratedVoice = user.save_designed_voice(temporaryVoiceID, newVoiceName)

except requests.exceptions.RequestException:
    print("Couldn't design voice, likely out of tokens or slots.")

```

## Play back and delete a history item

```python
from elevenlabslib import *
from elevenlabslib.helpers import *

api_key = "api_key"
user = User(api_key)

#Generate two items to be deleted later
premadeVoice = user.get_voices_by_name_v2("Rachel")[0]
premadeVoice.generate_audio_v3("Test.")
premadeVoice.generate_audio_v3("Test.")

#Find them, download them then delete them.
#Note - I'm assuming they're within the last 10 generations, since they were just created.
testItems = list()
for historyItem in user.get_history_items_paginated(maxNumberOfItems=10):
    if historyItem.text == "Test.":
        testItems.append(historyItem)

#Download them
downloadedItems = user.download_history_items_v2(testItems)

#Play them back
for historyID, downloadDataTuple in downloadedItems.items():
    play_audio_v2(downloadDataTuple[0], PlaybackOptions(runInBackground=False))

#Delete them
for item in testItems:
    item.delete()
```