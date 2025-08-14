from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medical-translator")

# --------- Optional grammar/medical enhancement model (T5-based) ----------
GEC_MODEL_ID = "vennify/t5-base-grammar-correction"
try:
    gec_tokenizer = AutoTokenizer.from_pretrained(GEC_MODEL_ID)
    gec_model = AutoModelForSeq2SeqLM.from_pretrained(GEC_MODEL_ID)
    USE_GEC = True
    logger.info("Loaded grammar correction model.")
except Exception as e:
    logger.warning(f"Grammar model unavailable, falling back to pass-through. Reason: {e}")
    gec_tokenizer = None
    gec_model = None
    USE_GEC = False

# --------- Translation model cache ----------
translation_cache: dict[str, tuple[AutoTokenizer, AutoModelForSeq2SeqLM]] = {}

SUPPORTED_LANGUAGES = {
    "ar": "Arabic", "de": "German", "es": "Spanish",
    "fr": "French", "hi": "Hindi", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "nl": "Dutch", "pl": "Polish", "ru": "Russian", "sv": "Swedish",
    "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese",
    "zh": "Chinese", "en": "English"
}

BCP47_BY_CODE = {
    "ar": "ar-SA","de": "de-DE","es": "es-ES",
    "fr": "fr-FR", "hi": "hi-IN", "id": "id-ID", "it": "it-IT",
    "ja": "ja-JP", "ko": "ko-KR", "nl": "nl-NL", "pl": "pl-PL",
    "ru": "ru-RU", "sv": "sv-SE", "th": "th-TH",
    "tr": "tr-TR", "uk": "uk-UA", "ur": "ur-PK", "vi": "vi-VN", "zh": "zh-CN", "en": "en-US"
}


@app.route("/")
def index():
    return send_from_directory(".", "home.html")


@app.route("/languages", methods=["GET"])
def languages():
    return jsonify({
        "languages": [
            {"code": code, "name": name, "bcp47": BCP47_BY_CODE.get(code, code)}
            for code, name in SUPPORTED_LANGUAGES.items()
        ]
    })


def load_translation_model(source_lang: str, target_lang: str):
    """Load/cached MarianMT model for source->target."""
    if source_lang == target_lang:
        raise ValueError("Source and target languages must be different.")

    model_id = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"
    if model_id in translation_cache:
        return translation_cache[model_id]

    try:
        tok = AutoTokenizer.from_pretrained(model_id)
        mdl = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        translation_cache[model_id] = (tok, mdl)
        logger.info(f"Loaded translation model: {model_id}")
        return tok, mdl
    except Exception as e:
        logger.warning(f"Direct model {model_id} unavailable: {e}")
        return None  # fallback via English will be handled


def run_translation(text: str, source_lang: str, target_lang: str) -> str:
    """Try direct translation; if unavailable, fallback via English."""

    # 1) Direct translation
    model = load_translation_model(source_lang, target_lang)
    if model:
        tok, mdl = model
        inputs = tok([text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            generated = mdl.generate(**inputs, max_new_tokens=128, num_beams=4, early_stopping=True)
        return tok.decode(generated[0], skip_special_tokens=True).strip()

    # 2) Fallback via English
    if source_lang != "en":
        model_to_en = load_translation_model(source_lang, "en")
        if not model_to_en:
            raise RuntimeError(f"No model found for {source_lang} → English")
        tok, mdl = model_to_en
        inputs = tok([text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            generated = mdl.generate(**inputs, max_new_tokens=128, num_beams=4, early_stopping=True)
        text_in_english = tok.decode(generated[0], skip_special_tokens=True).strip()
    else:
        text_in_english = text

    if target_lang == "en":
        return text_in_english

    model_from_en = load_translation_model("en", target_lang)
    if not model_from_en:
        raise RuntimeError(f"No model found for English → {target_lang}")
    tok, mdl = model_from_en
    inputs = tok([text_in_english], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        generated = mdl.generate(**inputs, max_new_tokens=128, num_beams=4, early_stopping=True)
    return tok.decode(generated[0], skip_special_tokens=True).strip()


def enhance_text(text: str, source_lang: str) -> str:
    """Enhance text only if source language is English."""
    if not text:
        return text
    if source_lang != "en" or not USE_GEC:
        return text.strip()
    try:
        inp = f"fix: {text.strip()}"
        inputs = gec_tokenizer([inp], return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = gec_model.generate(**inputs, max_new_tokens=128, num_beams=4, early_stopping=True)
        corrected = gec_tokenizer.decode(outputs[0], skip_special_tokens=True)
        return corrected.strip()
    except Exception as e:
        logger.warning(f"GEC failed, fallback to original. Reason: {e}")
        return text.strip()


@app.route("/process_text", methods=["POST"])
def process_text():
    try:
        data = request.get_json(force=True) or {}
        raw_text = (data.get("text") or "").strip()
        source_lang = (data.get("source_lang") or "en").lower()
        target_lang = (data.get("target_lang") or "es").lower()

        if not raw_text:
            return jsonify({"error": "No text provided"}), 400

        enhanced = enhance_text(raw_text, source_lang)
        translated = run_translation(enhanced, source_lang, target_lang)

        return jsonify({
            "enhanced_text": enhanced,
            "translated_text": translated,
            "tts_lang": BCP47_BY_CODE.get(target_lang, target_lang),
            "target_lang": target_lang
        })

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except RuntimeError as re:
        return jsonify({"error": str(re)}), 400
    except Exception as e:
        logger.exception("Processing failed")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
