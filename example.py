import io
import json
import os

import requests

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

    #Enable logging:
    logging.basicConfig(level=logging.DEBUG)

    #Create the user object
    user = ElevenLabsUser(apiKey)

    #Delete voices if they already exist
    try:
        user.get_voices_by_name("TESTNAME")[0].delete_voice()
        print("Voice found and deleted.")
    except IndexError:
        print("Voice not found, no need to delete it.")

    try:
        user.get_voices_by_name("newName")[0].delete_voice()
        print("Voice found and deleted.")
    except IndexError:
        print("Voice not found, no need to delete it.")



    if user.get_voice_clone_available():
        # Add a voice (uploading the sample from bytes):
        firstSampleBytes = open(samplePath1, "rb").read()

        # Get the filename of the first sample from the path to identify it:
        firstSampleFileName = samplePath1[samplePath1.rfind("\\") + 1:]

        #Create the new voice by uploading the sample as bytes
        newVoice = user.clone_voice_bytes("TESTNAME", {firstSampleFileName: firstSampleBytes})
        #This can also be done by using the path:
        #newVoice = user.create_voice_by_path("TESTNAME", samplePath1)

        #Get new voice data
        print("New voice:")
        print(newVoice.get_name())
        print(newVoice.voiceID)
        print(newVoice.get_samples()[0].fileName)

        #Play back the automatically generated preview:
        try:
            newVoice.play_preview(playInBackground=False)
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
        newVoice.add_samples_by_path([samplePath2])



        #Remove the first sample, playing it back before deleting it:
        for sample in newVoice.get_samples():
            #NOTE: You CANNOT find a sample by simply checking if the bytes match. There is some re-encoding (or tag stripping) going on server-side.
            if sample.fileName == firstSampleFileName:
                print("Found the sample we want to delete.")
                print(sample.fileName)
                sample.play_audio(playInBackground=False)
                print("Playback done (blocking)")

                firstPlaybackEnded = threading.Event()
                secondPlaybackEnded = threading.Event()
                #These two are both going to being to download data at the same time (not really because in samples and historyItems the bytes are cached, but still)
                #but will only play one at a time because of the events.

                #This is just a simple example of what can be done with the callbacks.

                print("Doing two playbacks back to back...")
                sample.play_audio(playInBackground=True, onPlaybackStart=firstPlaybackEnded.wait, onPlaybackEnd=secondPlaybackEnded.set)
                sample.play_audio(playInBackground=True, onPlaybackEnd=firstPlaybackEnded.set)
                print("Waiting for both playbacks to end...")
                secondPlaybackEnded.wait()
                sample.delete()

        #Change the voice name:
        newVoice.edit_voice(newName="newName")

        #Showcase how despite the name being changed, the initialName DOES NOT.
        print("newVoice.get_name(): " + newVoice.get_name())
        print("newVoice.initialName: " + newVoice.initialName)

        #Get the current voice settings:
        currentSettings = newVoice.get_settings()
        stability:float = currentSettings["stability"]
        similarityBoost:float = currentSettings["similarity_boost"]

        #Lower stability and increase similarity, then edit the voice settings:
        stability = min(1.0, stability-0.1)
        similarityBoost = min(1.0, similarityBoost + 0.1)
        newVoice.edit_settings(stability, similarityBoost)
        try:
            # Generate an output:
            newVoice.generate_and_play_audio("Test.",playInBackground=False)
            # Generate an output overwriting the stability and/or similarity setting for this generation:
            newVoice.generate_and_play_audio("Test.", stability=0.3,playInBackground=True)
        except requests.exceptions.RequestException:
            print("Couldn't generate output, likely out of tokens.")

        #Save the voice's current name:
        newVoiceName = newVoice.get_name()

        #Delete the new voice:
        newVoice.delete_voice()

        #Warning: The object still persists but its voiceID is now empty, so none of the methods will work.

        #Check that the voice was deleted:
        for voice in user.get_available_voices():
            voiceName = voice.initialName
            print(voiceName)
            assert(voiceName != newVoiceName)

    #Get one of the premade voices:
    #NOTE: get_voices_by_name returns a list of voices that match that name (since multiple voices can have the same name).
    premadeVoice = user.get_voices_by_name("Rachel")[0]
    try:
        #Playback in normal mode, waiting for the whole file to be downloaded before playing it back.
        premadeVoice.generate_and_play_audio("Test.", playInBackground=False, portaudioDeviceID=6)

        #Playback with streaming (without waiting for the whole file to be downloaded, so with a faster response time)
        #Additionally, the second one will begin downloading while the first one is still playing, but will only start playing once the first is done.
        firstPlaybackEnded = threading.Event()
        secondPlaybackEnded = threading.Event()
        print("Doing two STREAMED playbacks back to back...")
        premadeVoice.generate_and_stream_audio("Test One.", streamInBackground=True, onPlaybackEnd=firstPlaybackEnded.set)
        premadeVoice.generate_and_stream_audio("Test Two.", streamInBackground=True, onPlaybackStart=firstPlaybackEnded.wait, onPlaybackEnd=secondPlaybackEnded.set)

        print("Waiting for both playbacks to end...")
        secondPlaybackEnded.wait()

        #Generate a sample and save it to disk, then play it back.
        mp3Data = premadeVoice.generate_audio_bytes("Test.")
        save_bytes_to_path("test.wav",mp3Data)
        play_audio_bytes(open("test.wav","rb").read(),False,6)

        #Generate a sample and save it to a file-like object, then play it back.
        memoryFile = io.BytesIO()
        save_bytes_to_file_object(memoryFile, mp3Data, "ogg")
        memoryFile.seek(0)  #Seek the back to the beginning
        play_audio_bytes(memoryFile.read(), playInBackground=False)
    except requests.exceptions.RequestException:
        print("Couldn't generate an output, likely out of tokens.")

    #Let's change which API key we use to generate samples with this voice
    newUser = ElevenLabsUser(apiKey2)
    premadeVoice.linkedUser = newUser

    try:
        premadeVoice.generate_and_play_audio("Test.",playInBackground=False)
    except requests.exceptions.RequestException:
        print("Couldn't generate an output, likely out of tokens.")

    #Play back and delete the test items we created from both accounts:
    for account in [user, newUser]:
        for historyItem in account.get_history_items():
            if historyItem.text == "Test.":
                print("Found test history item, playing it back and deleting it.")
                historyItem.play_audio(playInBackground=False)
                historyItem.delete()


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

