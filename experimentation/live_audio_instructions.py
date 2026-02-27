import asyncio
import os
import pyaudio
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# --- Audio Configuration ---
# Gemini requires 16kHz, 16-bit PCM, Mono for INPUT
INPUT_RATE = 16000
# Gemini streams back 24kHz, 16-bit PCM, Mono for OUTPUT
OUTPUT_RATE = 24000
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1

async def main():
    # 1. Initialize the Vertex AI Client
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    client = genai.Client(
        vertexai=True,
        project=project_id,
        location=location
    )

    # 2. Configure PyAudio for microphone and speakers
    p = pyaudio.PyAudio()
    
    # Stream for capturing microphone audio
    input_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )
    
    # Stream for playing the AI's audio response
    output_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_RATE,
        output=True,
        frames_per_buffer=CHUNK_SIZE
    )

    print("🎙️ Starting Voice-to-Voice Live Session... Start speaking! (Press Ctrl+C to stop)")

    # 3. Configure the Live Session
    # Using the native audio model optimized for low-latency voice
    model_id = "gemini-live-2.5-flash-native-audio" 
    
    # Define the persona and rules for the session
    storyteller_prompt = (
        "You are an interactive and creative storyteller. "
        "I will participate in the story with you. Adapt the plot based on my spoken choices, "
        "use highly expressive and dramatic tones, and keep your responses relatively concise "
        "so we have a good back-and-forth conversational pace."
        "Try to get the following information from me: my name, age, gender and location. however blend it into the conversation naturally."
    )

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        # Inject the context securely using types.Content
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=storyteller_prompt)]
        )
    )

    # 4. Connect to the Multimodal Live API via WebSockets
    async with client.aio.live.connect(model=model_id, config=config) as session:
        
        # Task A: Read from the microphone and stream to Gemini
        async def send_audio():
            while True:
                # Read raw PCM data from the mic
                data = input_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                
                # Send the raw audio chunk to the model
                await session.send_realtime_input(
                    media=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )
                await asyncio.sleep(0.001)

        # Task B: Receive audio from Gemini and play it.
        async def receive_audio():
            while True:
                async for message in session.receive():
                    if message.server_content and message.server_content.model_turn:
                        for part in message.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                # Write the received audio chunks to the speakers
                                output_stream.write(part.inline_data.data)

        # Run both the sending and receiving tasks concurrently
        await asyncio.gather(send_audio(), receive_audio())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession ended by user.")