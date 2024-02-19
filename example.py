import io
import json
import os

import requests
import sounddevice

from elevenlabslib.helpers import *
from elevenlabslib import *

def main():
    if os.path.exists("config.json"):
        configData = json.load(open("config.json","r"))
        apiKey = configData["api_key"]
        apiKey2 = configData["api_key_2"]
        samplePath1 = configData["sample_path_1"]
        samplePath2 = configData["sample_path_2"]
    else:
        apiKey = ""
        apiKey2 = ""
        samplePath1 = ""
        samplePath2 = ""

    #Uncomment this to enable logging:
    #logging.basicConfig(level=logging.DEBUG)

    #Create the user object
    user = User(apiKey)

    #Delete voices if they already exist
    try:
        user.get_voices_by_name("ClonedVoiceTest")[0].delete_voice()
        print("Voice found and deleted.")
    except IndexError:
        print("Voice not found, no need to delete it.")

    try:
        user.get_voices_by_name("newName")[0].delete_voice()
        print("Voice found and deleted.")
    except IndexError:
        print("Voice not found, no need to delete it.")

    #Let's generate a new voice using voice design
    try:
        temporaryVoiceID, generatedAudio = user.design_voice(gender="female", accent="american", age="young", accent_strength=1.0)
    except requests.exceptions.RequestException:
        temporaryVoiceID = None
        generatedAudio = None
        print("Couldn't design voice, likely out of tokens.")
    if temporaryVoiceID is not None:
        play_audio_bytes_v2(generatedAudio, PlaybackOptions(runInBackground=False))

        #We have the audio sample for the new voice and the TEMPORARY voice ID. The voice is not yet saved to our account.
        #Let's play back the audio sample and then save the voice to the account.
        newGeneratedVoice = user.save_designed_voice(temporaryVoiceID, "DesignedVoiceTest")

        # Change the voice name and description:
        newGeneratedVoice.edit_voice(newName="newName", description="This is a test voice from example.py")

        # Showcase how despite the name being changed, the cached one DOES NOT.
        print("newGeneratedVoice.name: " + newGeneratedVoice.name)
        print("newGeneratedVoice.description: " + newGeneratedVoice.description)

        # If you want to get the updated ones, you have to do voice.update_data():
        newGeneratedVoice.update_data()
        print("newGeneratedVoice.name after update_data(): " + newGeneratedVoice.name)
        print("newGeneratedVoice.description after update_data(): " + newGeneratedVoice.description)
        # Get the current voice settings:
        currentSettings = newGeneratedVoice.settings
        stability: float = currentSettings["stability"]
        similarityBoost: float = currentSettings["similarity_boost"]

        # Show the raw voice metadata:
        print("Raw voice metadata:")
        print(newGeneratedVoice.update_data())


        # Lower stability and increase similarity, then edit the voice settings:
        stability = min(1.0, stability - 0.1)
        similarityBoost = min(1.0, similarityBoost + 0.1)
        newGeneratedVoice.edit_settings(stability, similarityBoost)
        try:
            # Generate an output:
            newGeneratedVoice.generate_play_audio_v2("Test.", playbackOptions=PlaybackOptions(runInBackground=False))
            # Generate an output overwriting the stability and/or similarity setting for this generation:
            newGeneratedVoice.generate_play_audio_v2("Test.", playbackOptions=PlaybackOptions(runInBackground=False), generationOptions=GenerationOptions(stability=0.3))
        except requests.exceptions.RequestException:
            print("Couldn't generate output, likely out of tokens.")

        # Save the voice's ID:
        storedVoiceID = newGeneratedVoice.voiceID

        #Delete the voice:
        newGeneratedVoice.delete_voice()
        # Warning: The object still persists but its voiceID is now empty, so none of the methods will work.

        # Check that the voice was deleted:
        for voice in user.get_available_voices():
            assert (voice.voiceID != storedVoiceID)


    if user.get_voice_clone_available() and False:
        # Add a voice (uploading the sample from bytes):
        firstSampleBytes = open(samplePath1, "rb").read()

        # Get the filename of the first sample from the path to identify it:
        firstSampleFileName = samplePath1[samplePath1.rfind("\\") + 1:]

        #Create the new voice by uploading the sample as bytes
        newClonedVoice = user.clone_voice_bytes("ClonedVoiceTest", {firstSampleFileName: firstSampleBytes})
        #This can also be done by using the path:
        #newClonedVoice = user.clone_voice_by_path("ClonedVoiceTest", samplePath1)

        #Get new voice data
        print("New voice:")
        print(newClonedVoice.name)
        print(newClonedVoice.voiceID)
        print(newClonedVoice.get_samples()[0].fileName)

        #Play back the automatically generated preview:
        try:
            newClonedVoice.play_preview_v2(PlaybackOptions(runInBackground=False))
        except RuntimeError:
            print("Error getting the preview. It likely hasn't been generated yet.")

        #Get a list of all cloned voices available to the account:
        print("New cloned voices:")
        for voice in user.get_available_voices():
            if voice.category == "cloned":
                #The .initialName property is the name the voice had at the time the object was created.
                #It's useful when iterating over all available voices like this, since it won't make a call to the API every time.
                print(voice.initialName)

        #Add a new sample to the voice:
        newClonedVoice.add_samples_by_path([samplePath2])



        #Remove the first sample, playing it back before deleting it:
        for sample in newClonedVoice.get_samples():
            #NOTE: You CANNOT find a sample by simply checking if the bytes match. There is some re-encoding (or tag stripping) going on server-side.
            if sample.fileName == firstSampleFileName:
                print("Found the sample we want to delete.")
                print(sample.fileName)
                sample.play_audio_v2(PlaybackOptions(runInBackground=False))
                print("Playback done (blocking)")

                firstPlaybackEnded = threading.Event()
                secondPlaybackEnded = threading.Event()
                #These two are both going to being to download data at the same time (not really because in samples and historyItems the bytes are cached, but still)
                #but will only play one at a time because of the events.

                #This is just a simple example of what can be done with the callbacks.

                print("Doing two playbacks back to back...")
                sample.play_audio_v2(PlaybackOptions(runInBackground=True, onPlaybackStart=firstPlaybackEnded.wait, onPlaybackEnd=secondPlaybackEnded.set))
                sample.play_audio_v2(PlaybackOptions(runInBackground=True, onPlaybackEnd=firstPlaybackEnded.set))
                print("Waiting for both playbacks to end...")
                secondPlaybackEnded.wait()
                sample.delete()
        #Delete the new cloned voice:
        newClonedVoice.delete_voice()


    #Get one of the premade voices:
    #NOTE: get_voices_by_name returns a list of voices that match that name (since multiple voices can have the same name).
    premadeVoice:Voice = user.get_voices_by_name("Rachel")[0]
    try:
        #Playback in normal mode, waiting for the whole file to be downloaded before playing it back, on a specific device.
        premadeVoice.generate_play_audio_v2("Test.", playbackOptions=PlaybackOptions(runInBackground=False, portaudioDeviceID=sounddevice.default.device))

        #Playback with streaming (without waiting for the whole file to be downloaded, so with a faster response time)
        #Additionally, the second one will begin downloading while the first one is still playing, but will only start playing once the first is done.
        firstPlaybackEnded = threading.Event()
        secondPlaybackEnded = threading.Event()
        print("Doing two STREAMED playbacks back to back...")

        premadeVoice.generate_stream_audio_v2("Test One.", playbackOptions=PlaybackOptions(runInBackground=True, onPlaybackEnd=firstPlaybackEnded.set))
        premadeVoice.generate_stream_audio_v2("Test Two.", playbackOptions=PlaybackOptions(runInBackground=True, onPlaybackStart=firstPlaybackEnded.wait, onPlaybackEnd=secondPlaybackEnded.set))

        print("Waiting for both playbacks to end...")
        secondPlaybackEnded.wait()

        #Generate a sample and save it to disk, then play it back.
        mp3Data = premadeVoice.generate_audio_v2("Test.")[0]
        save_audio_bytes(mp3Data, "test.wav","wav")
        play_audio_bytes_v2(open("test.wav","rb").read(), playbackOptions=PlaybackOptions(runInBackground=False, portaudioDeviceID=sounddevice.default.device))

        #Generate a sample and save it to a file-like object, then play it back.
        memoryFile = io.BytesIO()
        save_audio_bytes(mp3Data, memoryFile, "ogg")
        memoryFile.seek(0)  #Seek the back to the beginning
        play_audio_bytes_v2(open("test.wav", "rb").read(), playbackOptions=PlaybackOptions(runInBackground=False))
    except requests.exceptions.RequestException:
        print("Couldn't generate an output, likely out of tokens.")

    #Let's change which API key we use to generate samples with this voice
    newUser = User(apiKey2)
    premadeVoice.linkedUser = newUser

    try:
        premadeVoice.generate_play_audio_v2("Test.",playbackOptions=PlaybackOptions(runInBackground=False))
    except requests.exceptions.RequestException:
        print("Couldn't generate an output, likely out of tokens.")



    #Get, download and delete all the test generations
    testItems = dict()

    for account in [user, newUser]:
        testItems[account] = list()
        allItems = account.get_history_items_paginated(-1)
        for historyItem in allItems:
            if historyItem.text == "Test.":
                testItems[account].append(historyItem)

    downloadedItems = user.download_history_items_v2(testItems[user])
    downloadedItems2 = newUser.download_history_items_v2(testItems[newUser])

    # Delete them
    for account in [user, newUser]:
        for item in testItems[account]:
            item.delete()


def getNumber(prompt, minValue, maxValue) -> int:
    print(prompt)
    chosenVoiceIndex = -1
    while not (minValue <= chosenVoiceIndex <= maxValue):
        try:
            chosenVoiceIndex = int(input("Input a number between " + str(minValue) +" and " + str(maxValue)+"\n"))
        except:
            print("Not a valid number.")
    return chosenVoiceIndex

def chooseFromListOfStrings(prompt, options:list[str]) -> str:
    print(prompt)
    if len(options) == 1:
        print("Choosing the only available option: " + options[0])
        return options[0]

    for index, option in enumerate(options):
        print(str(index+1) + ") " + option)

    chosenOption = getNumber("", 1, len(options))-1
    return options[chosenOption]


if __name__ == "__main__":
    main()

