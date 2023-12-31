
import openai
from elevenlabs import set_api_key, generate

from middleware import logger

from credentials import get_cred_config

def check_auth_keys():
    creds = get_cred_config()
    
    if "ELEVEN_API_KEY" in creds:
        set_api_key(creds.get("ELEVEN_API_KEY"))
    else:
        logger.warning("eleven api key not found")

    if "OPENAI_API_KEY" in creds:
        openai.api_key = creds.get("OPENAI_API_KEY")
    else:
        logger.warning("openai api key not found")

def validate_response_length(response_length_value: int):
    return max(min(200, response_length_value), 5)

def transcribe_from_audio(audio_file):

    contents = audio_file.read()
    transcript = openai.Audio.transcribe_raw("whisper-1", contents, f"{audio_file.filename}.mp3")

    body_text = transcript.get('text', '')

    return body_text

def answer_my_question(question_text, existing_context = [], requested_response_length = 20):

    base_messages = [
        {"role": "system", "content": "Your name is Mr. Know-it-all. You are a polite and helpful teacher."},
        {"role": "user", "content": f"Excuse me, Mr. Know-it-all. I'd like to ask you a question. You answer should be simple, accurate, and {requested_response_length} words maximum. Answer kindly and politely like you're talking to a primary school student."},
        {"role": "assistant", "content": "Of course, ask me anything you'd like!"}
    ]

    is_user_message = True
    for chat_item in existing_context[-10:]: # only use the 10 most recent messages as part of the context
        new_message = {
            "role": "user" if is_user_message else "assistant",
            "content": chat_item or ''
        }
        is_user_message = not is_user_message
        base_messages.append(new_message)

    assert(is_user_message)

    base_messages.append({"role": "user", "content": question_text})

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=base_messages
    )

    output_message = response.get('choices')[0].get('message').get('content')

    return output_message

def sanitise_text(text: str) -> str:
    
    output = text.replace('\n', '')

    return output

def text_to_speech(text):

    audio = generate(text, voice='Sam')
    return audio
