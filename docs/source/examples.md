# Usage examples

## Play back, save and delete a generated audio

```python
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
premadeVoice = user.get_voices_by_name("Rachel")[0]

#Generate the audio and get the bytes and historyID. 
#The GenerationOptions specified here only apply for this generation.
generationData = premadeVoice.generate_play_audio_v2("This is a test.", PlaybackOptions(runInBackground=True), GenerationOptions(stability=0.4))

#Save them to disk, in ogg format (can be any format supported by SoundFile)
save_audio_bytes(generationData[0], "testAudio.ogg", outputFormat="ogg")

#Fetch the corresponding historyItem
historyItem = user.get_history_item(generationData[1])

#Rate it
historyItem.edit_feedback(thumbsUp=True,feedbackText="This text to speech service works very well!")

#Delete it
historyItem.delete()
```

## Speech to speech
```python
from elevenlabslib import *

user = ElevenLabsUser("YOUR_API_KEY")
voice = user.get_available_voices()[0]

#Note: As of right now, overriding parameters in a request (such as stability) does not work for s2s.
generation_options = GenerationOptions(model_id="eleven_english_sts_v2")

source_audio_file = open(r"C:\your\audio\file.mp3", "rb")
#sorce_audio can also be bytes, to allow you to pass input from a microphone:
source_audio_bytes = source_audio_file.read()

voice.generate_stream_audio_v2(source_audio_file, generationOptions=generation_options)
voice.generate_stream_audio_v2(source_audio_bytes, generationOptions=generation_options)
```

## Force the pronunciation of a word
```python
from elevenlabslib import *

user = ElevenLabsUser("YOUR_API_KEY")
voice = user.get_available_voices()[0]

#This means 'test' will be pronounced as 'tomato'.
forced_pronunciations = {
    "test":
        {
            "alphabet":"ipa",
            "pronunciation":"təˈmeɪtoʊ"
        }
}

voice.generate_stream_audio_v2("This is a test. Both instances of test will be pronounced as tomato.", playbackOptions=PlaybackOptions(runInBackground=False), generationOptions=GenerationOptions(model="eleven_monolingual_v1",forced_pronunciations=forced_pronunciations))

```

## Generate audio in PCM format
```python
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
premadeVoice = user.get_voices_by_name("Rachel")[0]

#pcm_highest (and mp3_highest) will automatically select the highest quality available to your account.
audioData = premadeVoice.generate_audio_v2("This is a test.", GenerationOptions(output_format="pcm_highest"))
```

## Use the Synthesizer utility class to manage playback
```python
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
voice = user.get_available_voices()[0]

#The synthesizer will manage streaming all the audio and playing it back in order.
synthesizer = Synthesizer()     
synthesizer.start()
for i in range(10):
    print(f"Loop {i}")
    synthesizer.add_to_queue(voice, f"This is test {i}.")

input("We're past the for loop already. Hit enter when you'd like to stop the playback.")
synthesizer.abort()

```

## Use input streaming with the OpenAI API
Adapted from [this example](https://gist.github.com/NN1985/a0712821269259061177c6abb08e8e0a) using the official wrapper.
```python
from elevenlabslib import *
import openai

client = openai.Client(api_key="your_openai_key_here")
#Using an AsyncClient is also supported - the library will handle the resulting async_generator.
user = ElevenLabsUser("your_elevenlabs_api_key")

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
# WARNING: The historyID will be "no_history_id_available", due to the API currently not returning it.
historyID, AudioStreamFuture = voice.generate_stream_audio_v2(
    text_stream, PlaybackOptions(runInBackground=False),
    GenerationOptions(latencyOptimizationLevel=4),
    WebsocketOptions(try_trigger_generation=True, chunk_length_schedule=[50])
)
```

## Generate an audio with the (alpha) V2 english model and its new settings

```python
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
premadeVoice = user.get_voices_by_name("Rachel")[0]

# Generate and play the audio using the English v2 model.
playbackOptions = PlaybackOptions(runInBackground=False)
generationOptions = GenerationOptions(model="eleven_english_v2", stability=0.3, similarity_boost=0.7, style=0.6,
                                      use_speaker_boost=True)
premadeVoice.generate_play_audio_v2("This is a test.", playbackOptions, generationOptions)
```

## Control the background playback of an audio

```python
import time
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
voice = user.get_voices_by_name("Rachel")[0]
usingStreaming = True
if usingStreaming:
    #The stream function uses a future rather than returing the audioStream directly.
    audioStreamFuture = voice.generate_stream_audio_v2("I am currently testing the playback control.", PlaybackOptions(runInBackground=True))[1]
    audioStream = audioStreamFuture.result()
else:
    audioStream = voice.generate_play_audio_v2("I am currently testing the playback control.", PlaybackOptions(runInBackground=True))[1]

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
user = ElevenLabsUser(api_key)
voice = user.get_voices_by_name("Rachel")[0]

#Get all available output devices
outputDevices = [device for device in sounddevice.query_devices() if device["max_output_channels"] > 0]

#Print them all to console
for device in outputDevices:
    print(f"Device id {device['index']}: {device['name']}")

#Choose one (randomly for this example) and use it.
outputDevice = random.choice(outputDevices)
print(f"Randomly chosen device: {outputDevice['name']}")

#WARNING: Since we're choosing it randomly, it may be invalid and cause errors.
voice.generate_stream_audio_v2("Device output test.", PlaybackOptions(runInBackground=False, portaudioDeviceID=outputDevice["index"]))
```

## Check if an audio file was generated with Elevenlabs

```python
from elevenlabslib.helpers import *

filePath = "audioFile.mp3"
audioBytes = open(filePath, "rb").read()

responseDict = run_ai_speech_classifier(audioBytes)
print(f"There's a {responseDict['probability'] * 100}% chance that this audio was AI generated.")
```

## Use the multilingual TTS model

```python
from elevenlabslib import *

api_key = "api_key"
user = ElevenLabsUser(api_key)
premadeVoice = user.get_voices_by_name("Rachel")[0]

#Find a multilingual model (one that supports a language other than english).
#We can't just check if it supports more than 1 language as english is split into 4 different types.
multilingualModel = None
for model in user.get_models():
    for language in model.supportedLanguages:
        if "en" not in language["language_id"]:
            #Found a model that supports a non-english language
            multilingualModel = model
            break

#Note: The model_id can also be directly used.
premadeVoice.generate_play_audio_v2("Questa è una prova!", PlaybackOptions(runInBackground=False), GenerationOptions(model=multilingualModel))
```

## Create and edit a cloned voice

```python
from elevenlabslib import *

api_key = "api_key"
newVoiceName = "newVoice"
user = ElevenLabsUser(api_key)

try:
    existingVoice = user.get_voices_by_name(newVoiceName)[0]
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
user = ElevenLabsUser(api_key)

try:
    #Generate the audio and get the temporary voiceID.
    temporaryVoiceID, generatedAudio = user.design_voice(gender="female", accent="american", age="young", accent_strength=1.0)
    
    #Play back the generated audio.
    play_audio_bytes_v2(generatedAudio, PlaybackOptions(runInBackground=False))
    
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
user = ElevenLabsUser(api_key)

#Generate two items to be deleted later
premadeVoice = user.get_voices_by_name("Rachel")[0]
premadeVoice.generate_audio_v2("Test.")
premadeVoice.generate_audio_v2("Test.")

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
    play_audio_bytes_v2(downloadDataTuple[0], PlaybackOptions(runInBackground=False))

#Delete them
for item in testItems:
    item.delete()
```