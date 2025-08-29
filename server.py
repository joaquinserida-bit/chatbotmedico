import os
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # permite llamadas desde Google Sites u otros orígenes

# ====== Memoria simple por usuario (en RAM) ======
conversations = {}  # user_id -> {"history": [...], "last_seen": datetime}

# ====== Conocimiento básico NO diagnóstico (educativo) ======
# Mapas de palabras clave a categorías y guías breves
SYMPTOM_KB = {
    "respiratorio": {
        "keywords": ["tos", "expectoración", "flema", "ahogo", "disnea", "ronquera", "pecho", "torácico", "respirar", "silbido"],
        "info": (
            "La tos persistente (>3 semanas), cambios en la voz/ronquera, falta de aire o dolor torácico "
            "pueden requerir evaluación. No siempre es cáncer: infecciones, asma, reflujo y hábitos también influyen."
        ),
        "followups": [
            "¿Desde cuándo tienes la tos o dificultad para respirar?",
            "¿Has notado tos con sangre o pérdida de peso?",
            "¿Fumas o has fumado antes? ¿Exposición a humo/polvo?",
            "¿La tos despierta por la noche o empeora con el esfuerzo?"
        ]
    },
    "digestivo_urinario": {
        "keywords": ["heces", "orina", "sangre en heces", "rectal", "diarrea", "estreñimiento", "cambio intestinal", "colon", "abdomen", "dolor abdominal", "reflujo", "acidez", "deglutir", "tragar", "ictericia", "amarillo"],
        "info": (
            "Cambios persistentes del hábito intestinal, sangre en heces, anemia, dolor abdominal que no cede o ictericia "
            "merecen evaluación clínica. También pueden deberse a dieta, infecciones o SII."
        ),
        "followups": [
            "¿Notas sangre roja o heces oscuras/pegajosas?",
            "¿Estos cambios llevan más de 3 semanas?",
            "¿Dolor al tragar o sensación de atasco de alimentos?",
            "¿Has tenido pérdida de apetito o saciedad precoz?"
        ]
    },
    "piel": {
        "keywords": ["lunar", "mancha", "melanoma", "cambio de color", "irregular", "sangra", "costra", "crecimiento", "ulcera"],
        "info": (
            "Un lunar que cambia (asimetría, bordes irregulares, color variado, diámetro >6 mm, evolución) o una lesión que "
            "sangra/no cicatriza debe revisarse con dermatología."
        ),
        "followups": [
            "¿El borde es irregular o los colores son diversos?",
            "¿Ha crecido rápido o cambia de forma?",
            "¿Pica, duele o sangra?",
            "¿Hay antecedentes familiares de cáncer de piel?"
        ]
    },
    "general": {
        "keywords": ["fatiga", "cansancio", "fiebre", "nocturna", "sudoración", "pérdida de peso", "anemia", "ganglios", "bulto", "masa"],
        "info": (
            "Síntomas generales como fatiga persistente, fiebre sin foco, sudoraciones nocturnas, ganglios que no ceden o "
            "pérdida de peso involuntaria requieren valoración médica, aunque tienen múltiples causas benignas."
        ),
        "followups": [
            "¿Cuánto peso has perdido y en cuánto tiempo?",
            "¿Los ganglios duelen o están duros/fijos?",
            "¿Las sudoraciones nocturnas te empapan la ropa con fiebre?",
            "¿Tomas algún medicamento o has tenido infecciones recientes?"
        ]
    },
    "gineco_urologico": {
        "keywords": ["mama", "bulto mamario", "pezón", "secreción", "útero", "ovario", "próstata", "testículo", "sangrado vaginal", "posmenopausia", "dolor testicular"],
        "info": (
            "Bultos mamarios nuevos, cambios del pezón/piel, sangrado vaginal anómalo (especialmente en posmenopausia) o "
            "bultos testiculares deben valorarse sin demora."
        ),
        "followups": [
            "¿El bulto es duro, fijo o con piel retraída?",
            "¿Hay secreción por pezón o cambios en la piel (piel de naranja)?",
            "¿Sangrado entre periodos o tras relaciones?",
            "¿Dolor o inflamación testicular repentina?"
        ]
    },
    "neuro": {
        "keywords": ["dolor de cabeza", "cefalea", "visión", "convulsión", "mareo", "debilidad", "entumecimiento", "habla", "memoria"],
        "info": (
            "Cefalea nueva/progresiva, convulsiones, cambios visuales, debilidad focal o alteraciones del habla/memoria "
            "necesitan valoración prioritaria."
        ),
        "followups": [
            "¿El dolor es nuevo, despierta por la noche o empeora al toser/esforzarte?",
            "¿Hay visión doble o pérdida visual?",
            "¿Has tenido debilidad de un lado del cuerpo o dificultad para hablar?",
            "¿Hubo traumatismo reciente?"
        ]
    }
}

# Señales de alarma (red flags) que aumentan urgencia
RED_FLAGS = [
    ("tos con sangre", ["sangre", "hemoptisis"]),
    ("sangrado en heces/orina", ["sangre en heces", "melenas", "rectal", "sangre en orina", "hematuria"]),
    ("pérdida de peso involuntaria", ["pérdida de peso", "bajé de peso sin querer"]),
    ("bulto duro/fijo o crecimiento rápido", ["bulto", "masa", "nódulo"]),
    ("dolor torácico persistente", ["dolor en el pecho", "dolor torácico"]),
    ("dificultad progresiva para tragar", ["no puedo tragar", "dificultad para tragar", "disfagia"]),
    ("ictericia (piel u ojos amarillos)", ["amarillo", "ictericia"]),
    ("fiebre prolongada o sudoración nocturna intensa", ["fiebre", "sudoración nocturna"]),
    ("convulsiones o déficit neurológico", ["convulsión", "pérdida de fuerza", "debilidad", "entumecimiento"]),
]

EMERGENCY_HINTS = [
    "dolor torácico intenso", "dificultad severa para respirar", "confusión aguda",
    "debilidad súbita en un lado", "convulsiones", "sangrado abundante", "pérdida de conciencia"
]

WELCOME_TEXT = (
    "Hola, soy tu asistente de salud virtual. Puedo orientarte sobre síntomas —con especial atención a señales de posible cáncer— "
    "de forma empática y clara. ⚠️ No doy diagnósticos; mi orientación es educativa y no sustituye a un profesional. "
    "Cuéntame qué sientes: duración, localización, intensidad y si hay cambios recientes."
)

# ====== Utilidades ======
def normalize(text: str) -> str:
    t = text.lower()
    # Quitar acentos básicos
    replacements = (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"))
    for a,b in replacements:
        t = t.replace(a,b)
    return t

def detect_categories(message_norm: str):
    found = []
    for cat, data in SYMPTOM_KB.items():
        if any(k in message_norm for k in map(normalize, data["keywords"])):
            found.append(cat)
    return found

def detect_red_flags(message_norm: str):
    flags = []
    for name, keys in RED_FLAGS:
        if any(normalize(k) in message_norm for k in keys):
            flags.append(name)
    return flags

def detect_emergency(message_norm: str):
    return any(normalize(k) in message_norm for k in EMERGENCY_HINTS)

def make_followups(categories):
    qs = []
    for c in categories:
        qs += SYMPTOM_KB[c]["followups"]
    # Evitar duplicados y no saturar
    unique = []
    for q in qs:
        if q not in unique:
            unique.append(q)
    return unique[:4]

def empathetic_intro(categories, flags):
    parts = ["Gracias por contarme lo que sientes. Entiendo que puede ser inquietante."]
    if categories:
        etiquetas = ", ".join(c.replace("_", " ") for c in categories)
        parts.append(f"Detecto indicios en estas áreas: {etiquetas}.")
    if flags:
        parts.append("Veo algunas señales que requieren atención:")
        parts.append(" • " + "\n • ".join(flags))
    return " ".join(parts)

def educational_bits(categories):
    if not categories:
        return ("Algunos síntomas pueden tener causas benignas (estrés, infecciones, hábitos), "
                "aunque es importante evaluarlos si persisten o empeoran.")
    snippets = []
    for c in categories[:3]:
        snippets.append(SYMPTOM_KB[c]["info"])
    return " ".join(snippets)

def closing_reco(flags, emergency=False):
    if emergency:
        return ("🚑 Por la descripción, podría tratarse de una urgencia. Te recomiendo acudir de inmediato a un servicio de emergencias "
                "o llamar al número local de urgencias. Si puedes, ve acompañado.")
    if flags:
        return ("📅 Te sugiero solicitar una cita prioritaria con tu médico. Lleva una lista de síntomas (inicio, duración, factores que "
                "empeoran/mejoran) y resultados previos si los tienes.")
    return ("🔎 Si los síntomas persisten >2–3 semanas, aumentan o te preocupan, agenda una valoración clínica. "
            "Mientras tanto, cuida hidratación, descanso y evita automedicación sin indicación.")

def build_response(user_text):
    msg_norm = normalize(user_text)
    categories = detect_categories(msg_norm)
    flags = detect_red_flags(msg_norm)
    emergency = detect_emergency(msg_norm)

    intro = empathetic_intro(categories, flags)
    edu = educational_bits(categories)
    followups = make_followups(categories) or [
        "¿Desde cuándo iniciaron los síntomas?",
        "¿Han cambiado recientemente (más frecuentes o intensos)?",
        "¿Hay pérdida de peso, fiebre o sudoraciones nocturnas?",
        "¿Tomas medicamentos o tienes antecedentes familiares relevantes?"
    ]
    reco = closing_reco(flags, emergency)

    return {
        "intro": intro,
        "education": edu,
        "followups": followups,
        "recommendation": reco
    }

def append_history(user_id, role, content):
    if user_id not in conversations:
        conversations[user_id] = {"history": [], "last_seen": datetime.utcnow()}
    conversations[user_id]["history"].append({"role": role, "content": content, "ts": datetime.utcnow().isoformat()})
    conversations[user_id]["last_seen"] = datetime.utcnow()

def get_recent_summary(user_id, last_n=6):
    hist = conversations.get(user_id, {}).get("history", [])
    return hist[-last_n:]

# ====== Rutas ======
@app.route("/", methods=["GET"])
def root():
    return "✅ Servidor educativo de Asistente Médico (Flask) en funcionamiento"

@app.route("/start", methods=["POST"])
def start():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id", "default")
    conversations[user_id] = {"history": [], "last_seen": datetime.utcnow()}
    append_history(user_id, "assistant", WELCOME_TEXT)
    return jsonify({"reply": WELCOME_TEXT, "history": get_recent_summary(user_id)})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id", "default")
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Mensaje vacío"}), 400

    # Iniciar hilo si no existe
    if user_id not in conversations:
        conversations[user_id] = {"history": [], "last_seen": datetime.utcnow()}
        append_history(user_id, "assistant", WELCOME_TEXT)

    append_history(user_id, "user", user_message)

    # Construir respuesta educativa
    analysis = build_response(user_message)

    # Redacción final (empática + estructurada)
    reply_parts = [
        analysis["intro"],
        "",
        "🧭 Orientación:",
        analysis["education"],
        "",
        "📝 Para entender mejor:",
        "• " + "\n• ".join(analysis["followups"]),
        "",
        analysis["recommendation"],
        "",
        "⚠️ Aviso: Esta información es educativa y no sustituye evaluación médica presencial."
    ]
    reply_text = "\n".join(reply_parts)

    append_history(user_id, "assistant", reply_text)
    return jsonify({
        "reply": reply_text,
        "flags_detected": analysis["intro"],
        "history": get_recent_summary(user_id)
    })

@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id", "default")
    conversations.pop(user_id, None)
    return jsonify({"status": "ok", "message": "Conversación reiniciada"})

# ====== Limpieza básica de sesiones antiguas (opcional) ======
@app.before_request
def cleanup_sessions():
    # Elimina sesiones sin actividad > 24h para no crecer en memoria
    cutoff = datetime.utcnow() - timedelta(hours=24)
    stale = [uid for uid, v in conversations.items() if v.get("last_seen", datetime.utcnow()) < cutoff]
    for uid in stale:
        conversations.pop(uid, None)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render asigna PORT
    app.run(host="0.0.0.0", port=port)

