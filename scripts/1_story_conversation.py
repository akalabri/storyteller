import asyncio
import os
import pyaudio
from google import genai
from google.genai import types
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# --- Audio Configuration ---
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1

# Words/phrases from the user that signal they want to end the session.
# The AI will give one last response, then the session closes automatically.
END_KEYWORDS = [
    "goodbye", "good bye", "bye bye", "that's all", "thats all",
    "we're done", "were done", "i'm done", "im done",
    "we are done", "that's enough", "thats enough",
    "end the story", "stop the story", "end session",
    "thank you that's all", "thanks that's all",
]

SYSTEM_PROMPT = """You are a warm, imaginative, and deeply creative storytelling companion. Your purpose is to craft a personalized 5-scene story for the person you're talking to — but you discover everything you need through genuine, flowing conversation, never through a formal list of questions.

Begin by greeting the user warmly and with curiosity. You are not conducting an interview; you are having a real conversation. Through that conversation, naturally and organically uncover:

- The kind of story they'd enjoy — genre and mood (e.g. funny, mysterious, educational, romantic, adventurous, scary, heartwarming, fantasy, sci-fi, historical, etc.)
- The world or setting of the story
- Characters they have in mind — names, personalities, relationships, appearances
- Specific details they care about — clothing, objects, special traits, cultural elements
- Any themes, messages, or ideas they want the story to carry

Do NOT ask about these as a checklist. Let the conversation breathe. Follow their lead. If they mention something interesting, explore it. React with genuine enthusiasm and curiosity. Ask natural follow-up questions the way a friend would.

You do not need all of this information before proceeding — once you feel you have a vivid enough picture to tell a meaningful story, naturally transition by saying something like "I think I have just what I need — shall I weave your story now?" or a similar warm, conversational signal. Then wait for their go-ahead, or proceed if the context makes it clear they're ready.

When you tell the story, narrate exactly 5 short, vivid scenes. Each scene should be 3–5 sentences, rich in imagery and emotion. Give each scene a short evocative title. Use an expressive, immersive voice — you are performing the story, not just reciting it.

After you finish the story, invite the user to respond: they might want to change something, continue the story, or simply react. Stay in the storyteller role and keep the conversation going naturally.

When the user signals they are done (says goodbye, that's all, we're done, etc.), give a warm and brief farewell, then end your response. The session will close automatically after your farewell."""

conversation_log = []


async def main():
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    client = genai.Client(
        vertexai=True,
        project=project_id,
        location=location
    )

    p = pyaudio.PyAudio()

    input_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )

    output_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_RATE,
        output=True,
        frames_per_buffer=CHUNK_SIZE
    )

    print("🎙️  Storyteller is ready — start speaking!")
    print("     Say 'goodbye', 'we're done', or 'that's all' to end the session.\n")

    model_id = "gemini-live-2.5-flash-native-audio"

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=SYSTEM_PROMPT)]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    # Set when the user says a goodbye phrase; cleared after AI replies once more.
    farewell_requested = asyncio.Event()
    # Set to actually stop all tasks after the AI's farewell turn completes.
    stop_event = asyncio.Event()

    async with client.aio.live.connect(model=model_id, config=config) as session:

        async def send_audio():
            while not stop_event.is_set():
                try:
                    data = input_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                except OSError:
                    # Buffer overflow or device error — skip this chunk and continue
                    await asyncio.sleep(0.01)
                    continue
                await session.send_realtime_input(
                    media=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )
                await asyncio.sleep(0.001)

        async def receive_audio():
            user_buf = []
            model_buf = []

            while not stop_event.is_set():
                async for message in session.receive():
                    if not message.server_content:
                        continue

                    sc = message.server_content

                    if sc.input_transcription and sc.input_transcription.text:
                        user_buf.append(sc.input_transcription.text)

                    if sc.output_transcription and sc.output_transcription.text:
                        model_buf.append(sc.output_transcription.text)

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                output_stream.write(part.inline_data.data)

                    if sc.turn_complete:
                        if user_buf:
                            user_text = "".join(user_buf).strip()
                            if user_text:
                                print(f"\n[You]: {user_text}")
                                conversation_log.append(("You", user_text))
                                # Check if the user is wrapping up
                                if any(kw in user_text.lower() for kw in END_KEYWORDS):
                                    farewell_requested.set()
                            user_buf.clear()

                        if model_buf:
                            model_text = "".join(model_buf).strip()
                            if model_text:
                                print(f"[Storyteller]: {model_text}\n")
                                conversation_log.append(("Storyteller", model_text))
                            model_buf.clear()

                        # If the AI just finished its farewell response, stop everything
                        if farewell_requested.is_set():
                            stop_event.set()
                            return

        await asyncio.gather(send_audio(), receive_audio())


def save_conversation():
    if not conversation_log:
        print("No conversation to save.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"story_conversation_{timestamp}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Story Conversation — {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        for speaker, text in conversation_log:
            f.write(f"{speaker}:\n{text}\n\n")

    print(f"✅ Conversation saved to {filename}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession ended early.")
    finally:
        save_conversation()
