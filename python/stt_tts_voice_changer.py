import azure.cognitiveservices.speech as tts
from vosk import Model, KaldiRecognizer
from threading import Lock, Thread
from os import makedirs, path
from time import time_ns
from queue import Queue
import pyaudio

# Speech Synthesis Markup Language (SSML) definition
# SSML is essentially just XML but for speech synthesis
ssml = """<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="en-US">
    <voice name="en-US-AshleyNeural">
        <prosody rate="medium" volume="x-loud" pitch="x-high">""" # Define voice parameters (speech speed, volume, pitch)
end_ssml = """
        </prosody>
    </voice>
</speak>"""

# This class's `write` function is called when TTS has converted text to audio
class AudioOutputStreamCallback(tts.audio.PushAudioOutputStreamCallback):
    def __init__(self, output_streams : list[pyaudio.Stream], buffer_size : int = 64): # High buffer size causes popping noises to be present in the background
        self.output_streams = output_streams
        self.buffer_size = buffer_size
        self.buffer = bytes()
        self.lock = Lock()

    def write(self, audio_buffer: memoryview) -> int:
        with self.lock:
            self.buffer += audio_buffer.tobytes()
            while len(self.buffer) >= self.buffer_size: # imma be completely honest, i have no clue why this stuff solves the stuttering issue, but it does
                chunk = self.buffer[:self.buffer_size]
                self.buffer = self.buffer[self.buffer_size:]
                for output_stream in self.output_streams:
                    output_stream.write(chunk)
        return len(audio_buffer)

# Simple function that outputs all available microphones in a neat list and allows the user to choose one
def obtain_mic(default_id : int = None) -> int:
    info = mic.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")

    print("\nPlease select a device ID from the following list:")
    for i in range(0, numdevices):
        if mic.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels") > 0:
            print(" * ", i, " - ", mic.get_device_info_by_host_api_device_index(0, i).get("name"))
    inp = input(" > ").strip()
    try:
        inp = int(inp)
        if inp > numdevices:
            raise IndexError("Invalid device ID")
    except Exception:
        if default_id:
            return default_id
        else:
            print("Invalid ID. Try again.")
            return obtain_mic()
    return inp

# Same as above but for output devices (speakers)
# Select CABLE Input to use Virtual Audio Cable and wire the outputted TTS to CABLE Output
def obtain_output(default_id : int = None) -> int:
    info = mic.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")

    print("\nPlease select a device ID from the following list:")
    for i in range(0, numdevices):
        if mic.get_device_info_by_host_api_device_index(0, i).get("maxOutputChannels") > 0:
            print(" * ", i, " - ", mic.get_device_info_by_host_api_device_index(0, i).get("name"))
    inp = input(" > ").strip()
    try:
        inp = int(inp)
        if inp > numdevices:
            raise IndexError("Invalid device ID")
    except Exception:
        if default_id:
            return default_id
        else:
            print("Invalid ID. Try again.")
            return obtain_output()
    return inp

# This function plays an AudioDataStream's data, however as the AudioDataStream can only be instantiated after the TTS has finished synthesizing
# audio, it is not used
#def play_audio(data_stream : tts.AudioDataStream):
#    chunk = 4096
#    audio_buffer = bytes(chunk)
#    while data_stream.read_data(audio_buffer) > 0:
#        output_stream.write(audio_buffer)

# Set up Kaldi Vosk recognizer for STT
# Download the model from https://alphacephei.com/vosk/models and place it in the "models" folder
model = Model("models/en-speech-small")
recognizer = KaldiRecognizer(model, 44100)

# PyAudio handles all the input and output data for audio
mic = pyaudio.PyAudio()
# Open a microphone input channel to take in audio data
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, output=True, input_device_index=obtain_mic(6), frames_per_buffer=4096)
stream.start_stream() # Start recording
# These are the two output streams
# One to play back to the user so they can hear what others are hearing
# And one to play into Virtual Audio Cable so it can be re-routed to "microphone" input
output_stream1 = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True, output_device_index=obtain_output(17))
output_stream2 = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True, output_device_index=9)

# Set up Azure TTS
# Change "SPEECH_KEY" and "SPEECH_REGION" to your Azure Speech Service key and region respectively
speech_config = tts.SpeechConfig(subscription="SPEECH_KEY", region="SPEECH_REGION")
#audio_config = tts.audio.AudioOutputConfig(use_default_speaker=True) # This would play the TTS to default output, but we want to wire it to two different output devices
stream_callback = AudioOutputStreamCallback([output_stream1, output_stream2]) # Instantiate a callback class instance
push_stream = tts.audio.PushAudioOutputStream(stream_callback) # Create an output stream using the callback instance
audio_config = tts.audio.AudioOutputConfig(stream=push_stream) # Make an output config that uses the output stream

# Use Ashley as Ashley is the TTS that Neuro-sama uses
speech_config.speech_synthesis_voice_name = "en-US-AshleyNeural"
# Create a synthesizer based off of the speech config and audio config
speech_synthesizer = tts.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

# Initialize the queue that will allow the two threads to communicate with each other
synthesis_queue = Queue()

# Speech synthesization (text-to-speech) thread
def synthesize():
    # Get time (in nanoseconds) since the Unix epoch to use as the folder for current data saving, since it's nearly guaranteed to be unique
    folder = time_ns()
    # Keep track of how many lines were saved so it doesn't overwrite pre-existing ones
    saved = 0
    while True:
        t = synthesis_queue.get() # Wait until Vosk STT model recognizes input and sends it to the synthesis queue
        if t is None: # Transcription thread sends None when "jarvis stop recording" is said
            break
        result = speech_synthesizer.speak_ssml_async(ssml + t + end_ssml).get() # Obtain the speech synthesis result
        if result.reason == tts.ResultReason.SynthesizingAudioCompleted:
            print("Speech synthesized for text [{}]".format(t))
            s_stream = tts.AudioDataStream(result) # Create an audio data stream from the result to save to a file
            # Saving data for later use (with RVC/for training a local TTS model that doesn't use Microsoft Azure)
            if not path.exists(f"models/training_data/{folder}"):
                makedirs(f"models/training_data/{folder}")
            s_stream.save_to_wav_file(f"models/training_data/{folder}/{saved}.wav")
            with open(f"models/training_data/{folder}/{saved}.txt", "w") as file:
                file.write(t)
            saved += 1 # Increment the saved variable
        elif result.reason == tts.ResultReason.Canceled: # Error logging
            cancellation_details = result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == tts.CancellationReason.Error:
                if cancellation_details.error_details:
                    print("Error details: {}".format(cancellation_details.error_details))
                    print("Did you set the speech resource key and region values?")
        synthesis_queue.task_done() # Remove the current entry from the synthesis queue, as it has now been synthesized

# Transcription (speech-to-text) thread
def record_and_transcribe():
    while True:
        data = stream.read(4096) # Read microphone input data from the mic stream
        if recognizer.AcceptWaveform(data): # Check if Vosk model has a transcription for the audio data
            text = recognizer.Result() # Get the text result of the audio data
            t = text[14:-3] # Remove useless parts of the text (first 14 characters and last 3 characters)
            if t.lower().startswith("jarvis stop recording"): # 
                print("\"jarvis stop recording\"\nStopping recording...")
                synthesis_queue.put_nowait(None)
                break
            if t.strip() not in ["", "huh"]: # Don't print or synthesize nothing (or "huh", which for some reason is transcribed when there is no voice)
                print(f"\"{t}\"") # Log synthesized text to console
                synthesis_queue.put_nowait(t) # Add text to synthesis queue for the synthesization thread

# Thread handling
def main():
    # Create threads for synthesization and transcription
    synthesization_thread = Thread(target=synthesize)
    speech_to_text_thread = Thread(target=record_and_transcribe)
    
    # Start both threads
    synthesization_thread.start()
    speech_to_text_thread.start()
    
    # Wait until threads stop ("jarvis stop recording")
    # This prevents the Python script from stopping prematurely due to the main thread having no work
    synthesization_thread.join()
    speech_to_text_thread.join()

# Start
main()

# Close everything when done
stream.stop_stream()
stream.close()
output_stream1.close()
output_stream2.close()
mic.terminate()