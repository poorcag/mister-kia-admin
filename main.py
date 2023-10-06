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

from parsing import transcribe_from_audio, check_auth_keys, answer_my_question, text_to_speech

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
    cats_count = context["cats_count"]
    dogs_count = context["dogs_count"]

    lead_team = ""
    vote_diff = 0
    leader_message = ""
    if cats_count != dogs_count:
        if cats_count > dogs_count:
            lead_team = "CATS"
            vote_diff = cats_count - dogs_count
        else:
            lead_team = "DOGS"
            vote_diff = dogs_count - cats_count
        leader_message = (
            f"{lead_team} are winning by {vote_diff} vote{'s' if vote_diff > 1 else ''}"
        )
    else:
        leader_message = "CATS and DOGS are evenly matched!"

    context["leader_message"] = leader_message
    context["lead_team"] = lead_team
    return render_template("index.html", **context)

@app.route("/ask/", methods=["POST"])
@jwt_authenticated
def ask_question() -> Response:
    audio_file = request.files['audio_file']

    logger.info(audio_file)
    logger.info(request.form)

    chat_context = request.form['chat_context']
    user_context = json.loads(chat_context)

    transcript = transcribe_from_audio(audio_file)

    answer = answer_my_question(transcript, user_context)

    answer_audio = text_to_speech(answer)

    logger.info(user_context)
    logger.info(answer)

    response_header = {
        "Content-Disposition": f"attachment; filename={audio_file.filename}",
        "filename": audio_file.filename,
        "transcription": transcript,
        "answer": answer,
        "file_size": str(len(answer_audio))
    }

    return Response(
        response=answer_audio,
        status=200,
        content_type="audio/mp3",
        headers=response_header
    )

@app.route("/", methods=["POST"])
@jwt_authenticated
def save_vote() -> Response:
    """Save a vote into the database."""
    # Get the team and time the vote was cast.
    team = request.form["team"]
    uid = request.uid
    time_cast = datetime.datetime.now(tz=datetime.timezone.utc)
    # Verify that the team is one of the allowed options
    if team != "CATS" and team != "DOGS":
        logger.warning(f"Invalid team: {team}")
        return Response(response="Invalid team specified.", status=400)

    try:
        database.save_vote(team=team, uid=uid, time_cast=time_cast)
    except Exception as e:
        # If something goes wrong, handle the error in this section. This might
        # involve retrying or adjusting parameters depending on the situation.
        logger.exception(e)
        return Response(
            status=500,
            response="Unable to successfully cast vote! Please check the "
            "application logs for more details.",
        )

    return Response(
        status=200,
        response=f"Vote successfully cast for '{team}' at time {time_cast}!",
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
