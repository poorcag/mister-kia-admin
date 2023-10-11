# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import signal
import sys
import json
from types import FrameType

from flask import Flask, render_template, request, Response

import database
import middleware
from middleware import jwt_authenticated, logger

from parsing import (
    transcribe_from_audio,
    check_auth_keys,
    answer_my_question,
    text_to_speech,
    sanitise_text,
    validate_response_length
)
from costs import calculate_query_cost

app = Flask(__name__, static_folder="static", static_url_path="")

app.config['MAX_CONTENT_PATH'] = 16 * 1024 * 1024 # 16mb should be heaps right?


@app.before_first_request
def create_table() -> None:
    """Initialize database connection and table on startup."""
    database.create_tables()
    """Ensure auth keys are set"""
    check_auth_keys()


@app.route("/", methods=["GET"])
def index() -> str:
    """Renders default UI with votes from database."""
    context = database.get_index_context()

    welcome_message = "Ask Mr. Know-It-All anything you'd like!"

    context["welcome_message"] = welcome_message
    return render_template("index.html", **context)

@app.route("/faq/", methods=["GET"])
def faq_page() -> str:
    return render_template("faq.html")

@app.route("/ask/", methods=["POST"])
@jwt_authenticated
def ask_question() -> Response:
    audio_file = request.files['audio_file']

    user_tokens = database.get_tokens_for_uid(request.uid)
    if user_tokens <= 0:
        return Response(status=500,
            response="Not enough tokens to ask a question!"
        )

    logger.info(audio_file)
    logger.info(request.form)

    chat_context = request.form['chat_context']
    user_context = json.loads(chat_context)

    try:
        requested_response_length = int(request.form['response_length'])
        clean_response_len = validate_response_length(requested_response_length)
    except:
        logger.info(f"Someone tried to give us {requested_response_length} as a response length")
        clean_response_len = 20

    transcript = transcribe_from_audio(audio_file)

    answer = answer_my_question(transcript, user_context, clean_response_len)

    token_cost = calculate_query_cost(answer)

    try:
        new_tokens = database.add_tokens_to_user(request.uid, -1 * token_cost)
    except:
        return Response(status=500,
            response="Something went wrong! User not found!"
        )

    try:
        answer_audio = text_to_speech(answer)
    except:
        return Response(status=500,
            response="Unable to perform text to speech"
        )
    
    sanitised_answer = sanitise_text(answer)

    response_header = {
        "Content-Disposition": f"attachment; filename={audio_file.filename}",
        "filename": audio_file.filename,
        "transcription": transcript,
        "cost": token_cost,
        "tokens": new_tokens,
        "answer": sanitised_answer,
        "file_size": str(len(answer_audio))
    }

    return Response(
        response=answer_audio,
        status=200,
        content_type="audio/mp3",
        headers=response_header
    )

@app.route("/initialise_user/", methods=["GET"])
@jwt_authenticated
def init_user() -> Response:
    try:
        database.initialise_user_if_required(request.uid)
    except:
        return Response(status=500,
                        response="Failed to initialise user")
    return Response(status=200)

@app.route("/tokens/", methods=["GET"])
@jwt_authenticated
def get_token_count() -> Response:
    uid = request.uid
    database.initialise_user_if_required(request.uid)
    try:
        token_count = database.get_tokens_for_uid(uid)
    except Exception as e:
        logger.exception(e)
        return Response(
            status=500,
            response="Unable to fetch token count",
        )
    return Response(
        status=200,
        response=str(token_count),
    )

@app.route("/tokens/", methods=["PUT"])
@jwt_authenticated
def add_tokens() -> Response:
    uid = request.uid
    database.initialise_user_if_required(request.uid)

    try:
        new_token_count = database.add_tokens_to_user(uid, 50)
    except Exception as e:
        logger.exception(e)
        return Response(
            status=500,
            response="Unable to add tokens to user",
        )
    return Response(
        status=200,
        response=str(new_token_count),
    )


# https://cloud.google.com/blog/topics/developers-practitioners/graceful-shutdowns-cloud-run-deep-dive
# [START cloudrun_sigterm_handler]
def shutdown_handler(signal: int, frame: FrameType) -> None:
    """Gracefully shutdown app."""
    logger.info("Signal received, safely shutting down.")
    database.shutdown()
    middleware.logging_flush()
    print("Exiting process.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    # handles Ctrl-C locally
    signal.signal(signal.SIGINT, shutdown_handler)

    app.run(host="127.0.0.1", port=8080, debug=True)
else:
    # handles Cloud Run container termination
    signal.signal(signal.SIGTERM, shutdown_handler)
# [END cloudrun_sigterm_handler]
