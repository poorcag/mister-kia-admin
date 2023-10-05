const rec_state = {
    AWAITING : 0,
    RECORDING : 1,
    RESPONDING : 2
}

let cur_state = rec_state.AWAITING
let isResponding = false
let chatContext = []
let mediaRecorder;

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
function getRandomInt(max) {
    return Math.floor(Math.random() * max);
}

async function askMisterKnowitall() {
    if (cur_state == rec_state.AWAITING) {
        startRecording();
    } else if (cur_state == rec_state.RECORDING) {
        stopRecording();
    } else if (cur_state == rec_state.RESPONDING) {
        
    }
}

function setButtonState(new_state) {
    if (new_state == rec_state.AWAITING) {
        // TODO reset the page state to neutral
    }
    else if (new_state == rec_state.RECORDING) {
        // TODO make page state recording
    }
    else if (new_state == rec_state.RESPONDING) {
        // TODO make page state responding
    }
    cur_state = new_state
}

async function handleFinishRecording() {

    const blob = new Blob(chunks, { type: 'audio/mp3' });
    const url = URL.createObjectURL(blob);
    console.log(url);

    console.log(chunks)

    const formData = new FormData()
    formData.append("audio_file", blob)
    formData.append('chat_context', JSON.stringify(chatContext));

    try {
        const token = await firebase.auth().currentUser.getIdToken();
        const response = await fetch('/ask/', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
            },
            body: formData,
        });
        if (response.ok) {
            const blob = await response.blob();
            const objectURL = URL.createObjectURL(blob);
            const audioElement = new Audio();
            audioElement.addEventListener("ended", () => { setButtonState(rec_state.AWAITING); }, false);
            audioElement.src = objectURL;
            audioElement.play();
        }
        else {
            setButtonState(rec_state.AWAITING);
        }
    } catch (err) {
        console.log(`Error when finishing recording: ${err}`);
        window.alert('Something went wrong... Please try again!');
        setButtonState(rec_state.AWAITING);
    }
}

async function startRecording() {
    if (firebase.auth().currentUser) {
        console.log("Starting recording")
        setButtonState(rec_state.RECORDING)
        chunks = [];
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => chunks.push(e.data);
        mediaRecorder.onstop = handleFinishRecording
        mediaRecorder.start();
    } else {
        window.alert('User not signed in.');
    }
}

async function stopRecording() {
    setButtonState(rec_state.RESPONDING);
    console.log("stopping recording")
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
    }
}

navigator.mediaDevices.getUserMedia({ audio: true })
    .then(function (stream) {
        console.log('You let me use your mic!')
    })
    .catch(function (err) {
        console.log('No mic for you!')
    });