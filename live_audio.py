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
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO]
    )

    # 4. Connect to the Multimodal Live API via WebSockets
    async with client.aio.live.connect(model=model_id, config=config) as session:
        
        # Task A: Read from the microphone and stream to Gemini
        async def send_audio():
            while True:
                # Read raw PCM data from the mic
                data = input_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                
                # Send the raw audio chunk to the model
                # (Voice Activity Detection is handled automatically by the API)
                await session.send(input=data, mime_type="audio/pcm")
                
                # Yield control back to the async event loop
                await asyncio.sleep(0.001) 

        # Task B: Receive audio chunks from Gemini and play them
        async def receive_audio():
            async for message in session.receive():
                # Check if the server sent model content back
                if message.server_content and message.server_content.model_turn:
                    for part in message.server_content.model_turn.parts:
                        # Extract and play the raw PCM audio bytes as they arrive
                        if part.inline_data and part.inline_data.data:
                            output_stream.write(part.inline_data.data)

        # Run both the sending and receiving tasks concurrently
        await asyncio.gather(send_audio(), receive_audio())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession ended by user.")