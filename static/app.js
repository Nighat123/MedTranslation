// Basic language list (BCP-47 tags). Extend as needed.
const LANGUAGES = [
  { code: "auto", name: "Auto-detect (input)" },
  { code: "en-US", name: "English (United States)" },
  { code: "es-ES", name: "Spanish (Spain)" },
  { code: "es-MX", name: "Spanish (Mexico)" },
  { code: "fr-FR", name: "French" },
  { code: "de-DE", name: "German" },
  { code: "it-IT", name: "Italian" },
  { code: "pt-PT", name: "Portuguese" },
  { code: "pt-BR", name: "Portuguese (Brazil)" },
  { code: "ar-SA", name: "Arabic" },
  { code: "hi-IN", name: "Hindi" },
  { code: "ur-PK", name: "Urdu" },
  { code: "zh-CN", name: "Chinese (Simplified)" },
  { code: "ja-JP", name: "Japanese" },
  { code: "ko-KR", name: "Korean" },
];

const inputLang = document.getElementById("inputLang");
const outputLang = document.getElementById("outputLang");
const micBtn = document.getElementById("micBtn");
const recordBtn = document.getElementById("recordBtn");
const clearBtn = document.getElementById("clearBtn");
const originalEl = document.getElementById("original");
const translatedEl = document.getElementById("translated");
const statusEl = document.getElementById("status");
const speakBtn = document.getElementById("speakBtn");
const audioPlayer = document.getElementById("audioPlayer");
const voiceSelect = document.getElementById("voiceSelect");
const formatSelect = document.getElementById("formatSelect");
const useBrowserTTSCb = document.getElementById("useBrowserTTS");
const copyOriginalBtn = document.getElementById("copyOriginal");
const copyTranslatedBtn = document.getElementById("copyTranslated");

// Populate language selectors
function populateLanguages() {
  inputLang.innerHTML = "";
  outputLang.innerHTML = "";
  LANGUAGES.forEach((l) => {
    const optIn = document.createElement("option");
    optIn.value = l.code;
    optIn.textContent = l.name;
    inputLang.appendChild(optIn);

    if (l.code !== "auto") {
      const optOut = document.createElement("option");
      optOut.value = l.code;
      optOut.textContent = l.name;
      outputLang.appendChild(optOut);
    }
  });
  inputLang.value = "auto";
  outputLang.value = "es-ES"; // default to Spanish
}
populateLanguages();

let isMicActive = false;
let recognition = null;
let mediaRecorder = null;
let recordedChunks = [];
let fullOriginalTranscript = "";
let fullTranslatedTranscript = "";
let lastTranslatedText = "";

// Helper UI
function setStatus(msg, type = "") {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (type ? ` ${type}` : "");
}

function appendOriginal(text) {
  if (!text) return;
  fullOriginalTranscript += (fullOriginalTranscript ? "\n" : "") + text;
  originalEl.textContent = fullOriginalTranscript;
  originalEl.scrollTop = originalEl.scrollHeight;
}

function appendTranslated(text) {
  if (!text) return;
  fullTranslatedTranscript += (fullTranslatedTranscript ? "\n" : "") + text;
  translatedEl.textContent = fullTranslatedTranscript;
  translatedEl.scrollTop = translatedEl.scrollHeight;
  lastTranslatedText = text;
}

function clearTranscripts() {
  fullOriginalTranscript = "";
  fullTranslatedTranscript = "";
  lastTranslatedText = "";
  originalEl.textContent = "";
  translatedEl.textContent = "";
}

// Translation via backend
async function translateText(text) {
  const source = inputLang.value === "auto" ? null : inputLang.value;
  const target = outputLang.value || "en-US";
  const body = {
    text,
    source_lang: source,
    target_lang: target,
  };
  try {
    const res = await fetch("/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    return data.translated_text;
  } catch (e) {
    console.error("Translate error:", e);
    setStatus(`Translate failed: ${e.message}`, "error");
    return "";
  }
}

// Start/stop real-time recognition using Web Speech API
function getSpeechRecognition() {
  const SR =
    window.SpeechRecognition ||
    window.webkitSpeechRecognition ||
    window.mozSpeechRecognition ||
    window.msSpeechRecognition;
  return SR ? new SR() : null;
}

function startMic() {
  if (isMicActive) return;
  recognition = getSpeechRecognition();
  if (!recognition) {
    setStatus("Web Speech API not supported. Use 'Record (Fallback)'.", "warn");
    return;
  }

  const lang = inputLang.value === "auto" ? "en-US" : inputLang.value;
  recognition.lang = lang;
  recognition.interimResults = true;
  recognition.continuous = true;

  recognition.onstart = () => {
    isMicActive = true;
    micBtn.textContent = "Stop Mic";
    micBtn.classList.add("listening");
    micBtn.setAttribute("aria-pressed", "true");
    setStatus(`Listening (${lang})...`);
  };
  recognition.onerror = (e) => {
    console.error("Recognition error:", e.error);
    setStatus(`Mic error: ${e.error}`, "error");
  };
  recognition.onend = () => {
    isMicActive = false;
    micBtn.textContent = "Start Mic";
    micBtn.classList.remove("listening");
    micBtn.setAttribute("aria-pressed", "false");
    setStatus("Mic stopped.");
  };
  let interim = "";

  recognition.onresult = async (event) => {
    let finalText = "";
    interim = "";

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      if (res.isFinal) {
        finalText += res[0].transcript.trim() + " ";
      } else {
        interim += res[0].transcript;
      }
    }

    // Show interim
    const display = fullOriginalTranscript + (interim ? "\n" + interim : "");
    originalEl.textContent = display;
    originalEl.scrollTop = originalEl.scrollHeight;

    // On final chunk: append and translate
    finalText = finalText.trim();
    if (finalText) {
      appendOriginal(finalText);
      const translated = await translateText(finalText);
      if (translated) appendTranslated(translated);
    }
  };

  try {
    recognition.start();
  } catch (e) {
    console.warn("Recognition start error:", e);
  }
}

function stopMic() {
  if (recognition && isMicActive) {
    recognition.stop();
  }
}

// Fallback: Record via MediaRecorder and send to /stt
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstart = () => {
      setStatus("Recording (fallback)... Press again to stop.");
      recordBtn.classList.add("recording");
    };
    mediaRecorder.onstop = async () => {
      recordBtn.classList.remove("recording");
      setStatus("Processing audio...");
      const blob = new Blob(recordedChunks, { type: "audio/webm" });
      await sendForTranscription(blob);
      setStatus("Ready.");
      stream.getTracks().forEach((t) => t.stop());
      mediaRecorder = null;
      recordBtn.textContent = "Record (Fallback)";
    };
    mediaRecorder.start();
    recordBtn.textContent = "Stop Recording";
  } catch (e) {
    console.error("Recording error:", e);
    setStatus(`Recording error: ${e.message}`, "error");
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

async function sendForTranscription(blob) {
  try {
    appendOriginal("(uploading audio...)");
    const form = new FormData();
    const file = new File([blob], "speech.webm", { type: "audio/webm" });
    form.append("file", file);
    const res = await fetch("/stt", { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    const text = data.text?.trim();
    if (text) {
      appendOriginal(text);
      const translated = await translateText(text);
      if (translated) appendTranslated(translated);
    }
  } catch (e) {
    console.error("STT error:", e);
    setStatus(`STT failed: ${e.message}`, "error");
  }
}

// TTS: server or browser
async function speakTranslated() {
  const text = lastTranslatedText || fullTranslatedTranscript.trim();
  if (!text) {
    setStatus("Nothing to speak yet.", "warn");
    return;
  }

  if (useBrowserTTSCb.checked && "speechSynthesis" in window) {
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = outputLang.value || "en-US";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
    setStatus("Speaking (browser)...");
    return;
  }

  // Server TTS
  try {
    const body = {
      text,
      voice: voiceSelect.value || "alloy",
      format: formatSelect.value || "mp3",
    };
    const res = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    audioPlayer.hidden = false;
    audioPlayer.src = url;
    audioPlayer.play();
    setStatus("Speaking (server)...");
  } catch (e) {
    console.error("TTS error:", e);
    setStatus(`TTS failed: ${e.message}`, "error");
  }
}

// Event handlers
micBtn.addEventListener("click", () => {
  if (!isMicActive) startMic();
  else stopMic();
});

recordBtn.addEventListener("click", () => {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    startRecording();
  } else {
    stopRecording();
  }
});

clearBtn.addEventListener("click", () => {
  clearTranscripts();
  setStatus("Cleared.");
});

speakBtn.addEventListener("click", speakTranslated);

copyOriginalBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(fullOriginalTranscript || "");
  setStatus("Original transcript copied.");
});
copyTranslatedBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(fullTranslatedTranscript || "");
  setStatus("Translated transcript copied.");
});

// Change recognition language when inputLang changes (if running)
inputLang.addEventListener("change", () => {
  if (isMicActive) {
    stopMic();
    setTimeout(startMic, 300);
  }
});