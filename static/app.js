(function () {
  const $ = (id) => document.getElementById(id);

  const sourceLangEl = $("sourceLang");
  const targetLangEl = $("targetLang");
  const useBrowserASREl = $("useBrowserASR");
  const resetBtn = $("resetBtn");
  const speakBtn = $("speakBtn");
  const recordBtn = $("recordBtn");
  const originalEl = $("original");
  const translatedEl = $("translated");
  const correctedBox = $("correctedBox");
  const correctedEl = $("corrected");
  const asrLabel = $("asrLabel");

  let original = "";
  let corrected = "";
  let translated = "";
  let isRecognizing = false;
  let useBrowserASR = false;
  let canBrowserASR = false;

  // Speech recognition setup (if available)
  const w = window;
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
  canBrowserASR = !!SR;
  useBrowserASR = canBrowserASR;
  useBrowserASREl.checked = useBrowserASR;
  asrLabel.textContent = "Use browser speech recognition" + (canBrowserASR ? "" : " (unavailable in this browser)");

  // Debounce helper
  function debounce(fn, delay) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  }

  // State updates
  function updateOriginal(text) {
    original = text;
    originalEl.textContent = text.trim() ? text : "Speak to begin…";
  }

  function updateTranslated(text) {
    translated = text;
    translatedEl.textContent = text.trim() ? text : "Translation will appear here…";
    speakBtn.disabled = !translated.trim();
  }

  function updateCorrected(text) {
    corrected = text;
    if (corrected && corrected.trim() && corrected.trim() !== original.trim()) {
      correctedBox.classList.remove("hidden");
      correctedEl.textContent = corrected;
    } else {
      correctedBox.classList.add("hidden");
      correctedEl.textContent = "";
    }
  }

  // API calls
  async function translateNow(text, sourceLang, targetLang) {
    if (!text.trim()) return;
    try {
      const res = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, sourceLang, targetLang })
      });
      if (!res.ok) throw new Error("Translation failed");
      const data = await res.json();
      updateCorrected(data.corrected_source || text);
      updateTranslated(data.translation || "");
    } catch (err) {
      console.error(err);
    }
  }

  const translateDebounced = debounce(translateNow, 400);

  // Browser Speech Recognition flow
  let rec = null;
  function startBrowserRecognition() {
    if (!canBrowserASR) return;
    rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = sourceLangEl.value;

    rec.onresult = (event) => {
      let interim = "";
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += t;
        else interim += t;
      }
      const combined = (original + finalText + interim).trim();
      updateOriginal(combined);
      translateDebounced(combined, sourceLangEl.value, targetLangEl.value);
    };

    rec.onerror = (e) => {
      console.error("SR error", e.error);
      isRecognizing = false;
      recordBtn.classList.remove("recording");
    };
    rec.onend = () => {
      isRecognizing = false;
      recordBtn.classList.remove("recording");
    };

    rec.start();
    isRecognizing = true;
    recordBtn.classList.add("recording");
  }

  function stopBrowserRecognition() {
    if (rec) {
      rec.stop();
      rec = null;
    }
    isRecognizing = false;
    recordBtn.classList.remove("recording");
  }

  // Server "hold-to-record" flow
  let mediaStream = null;
  let mediaRecorder = null;
  let chunks = [];

  async function startServerRecord() {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(mediaStream, { mimeType: "audio/webm" });
      chunks = [];
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        try {
          const blob = new Blob(chunks, { type: "audio/webm" });
          const fd = new FormData();
          fd.append("audio", blob, "audio.webm");
          fd.append("sourceLang", sourceLangEl.value);
          const res = await fetch("/api/transcribe", { method: "POST", body: fd });
          if (!res.ok) throw new Error("Transcription failed");
          const data = await res.json();
          const newText = (data.text || "").trim();
          if (newText) {
            const combined = (original + (original ? " " : "") + newText).trim();
            updateOriginal(combined);
            await translateNow(combined, sourceLangEl.value, targetLangEl.value);
          }
        } catch (err) {
          console.error(err);
        } finally {
          if (mediaStream) {
            mediaStream.getTracks().forEach((t) => t.stop());
            mediaStream = null;
          }
        }
      };
      mediaRecorder.start();
      isRecognizing = true;
      recordBtn.classList.add("recording");
    } catch (err) {
      console.error("Mic error", err);
    }
  }

  function stopServerRecord() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    isRecognizing = false;
    recordBtn.classList.remove("recording");
  }

  // TTS
  let cachedVoices = [];
  function loadVoices() {
    cachedVoices = window.speechSynthesis.getVoices();
  }
  loadVoices();
  if (typeof window !== "undefined") {
    window.speechSynthesis.onvoiceschanged = loadVoices;
  }

  function speak(text, lang) {
    if (!text) return;
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = lang;
    const match = cachedVoices.find((v) => (v.lang || "").toLowerCase() === lang.toLowerCase());
    if (match) utter.voice = match;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  }

  // UI events
  resetBtn.addEventListener("click", () => {
    updateOriginal("");
    updateTranslated("");
    updateCorrected("");
  });

  useBrowserASREl.addEventListener("change", (e) => {
    useBrowserASR = !!e.target.checked && canBrowserASR;
    useBrowserASREl.checked = useBrowserASR;
    asrLabel.textContent = "Use browser speech recognition" + (canBrowserASR ? "" : " (unavailable in this browser)");
  });

  speakBtn.addEventListener("click", () => {
    speak(translated, targetLangEl.value);
  });

  recordBtn.addEventListener("click", () => {
    // Click toggles only for browser ASR (continuous)
    if (useBrowserASR) {
      if (isRecognizing) stopBrowserRecognition();
      else startBrowserRecognition();
    }
  });

  // Hold-to-record for server mode
  function attachHoldEvents(el) {
    el.addEventListener("mousedown", () => { if (!useBrowserASR) startServerRecord(); });
    el.addEventListener("mouseup", () => { if (!useBrowserASR) stopServerRecord(); });
    el.addEventListener("mouseleave", () => { if (!useBrowserASR && isRecognizing) stopServerRecord(); });
    el.addEventListener("touchstart", () => { if (!useBrowserASR) startServerRecord(); }, { passive: true });
    el.addEventListener("touchend", () => { if (!useBrowserASR) stopServerRecord(); });
  }
  attachHoldEvents(recordBtn);
})();