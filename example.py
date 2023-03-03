import io
import json
import os

import elevenlabslib.helpers
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

    #Create the user object
    user = ElevenLabsUser(apiKey)

    #Add a voice (uploading the sample from bytes):
    firstSampleBytes = open(samplePath1,"rb").read()

    #Delete voice if it exists already
    try:
        user.get_voices_by_name("TESTNAME")[0].delete_voice()
        print("Voice found and deleted.")
    except:
        print("Voice not found, no need to delete it.")

    try:
        user.get_voices_by_name("newName")[0].delete_voice()
        print("Voice found and deleted.")
    except:
        print("Voice not found, no need to delete it.")

    # Get the filename of the first sample from the path to identify it:
    firstSampleFileName = samplePath1[samplePath1.rfind("\\") + 1:]

    if user.get_voice_clone_available():
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
        except:
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
            newVoice.generate_audio_bytes("Test.")
            # Generate an output overwriting the stability and/or similarity setting for this generation:
            newVoice.generate_audio_bytes("Test.", stability=0.3)
        except:
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
    print("")
    #Playback in blocking mode.
    premadeVoice.generate_and_play_audio("This is a test to see how much faster the playback is when using the streaming method.", playInBackground=False, portaudioDeviceID=6)

    #Playback with streaming (faster response time for longer files)
    premadeVoice.generate_and_stream_audio("This is a test to see how much faster the playback is when using the streaming method.", 6)
    print("FUCK")
    #Generate a test sample
    try:
        premadeVoice.generate_and_play_audio("Test.",playInBackground=False)
    except:
        print("Couldn't generate an output, likely out of tokens.")

    #Let's change which API key we use to generate samples with this voice
    newUser = ElevenLabsUser(apiKey2)
    premadeVoice.linkedUser = newUser

    try:
        premadeVoice.generate_and_play_audio("Test.",playInBackground=False)
    except:
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

#This function uses pydub (and io) to convert the bytes of an mp3 file to the bytes of a wav file.
#I use it so I can play back the audio using pyaudio instead of pydub (which allows you to choose the output device).



if __name__ == "__main__":
    main()

