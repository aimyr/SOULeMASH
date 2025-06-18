import os, json, base64, requests
from typing import Dict, List, Optional

from apify_client import ApifyClient
from openai import OpenAI
from pathlib import Path
import requests, tempfile
import json, re


# ==================== KEYS & CLIENTS ====================
APIFY_TOKEN     = os.getenv("APIFY_TOKEN",  "apify_api_RAgg1rLfDSMylWYQT2jUotIVsdWVyZ1jRj1P")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "sk-5XBRs-SSoSScHCXPeRij8JvO_KXHT2mc_Y6n0e7M7qT3BlbkFJvyiweBPGWuzj_fLKGCPw8eKnVN2Scd5gUW7NLaEycA")

apify  = ApifyClient(APIFY_TOKEN)
openai = OpenAI(api_key=OPENAI_API_KEY)

# ==================== PROMPTS ====================
ITEM_PROMPT = (
    "Ты — эксперт-психолог и культуролог. Проанализируй соц-контент по критериям:\n"
    "- Интересы\n- Тип личности (MBTI / Big Five)\n- Склонность к диалогу\n- Ценности\n"
    "Отвечай структурировано ровно этими четырьмя пунктами."
)
SUMMARY_PROMPT = (
     "Questions\n"
    "1) Что тебе ближе? (можешь отвечать своими словами!)\n"
    "1.Быть в центре внимания, 2.Сидеть в сторонке и наблюдать\n"
    "2) Когда кто-то грустит, ты:\n"
    "1.Сильно сопереживаешь, 2.Пропускаешь мимо\n"
    "3) Как ты относишься к новым идеям?\n"
    "1.Обожаю экспериментировать, 2.Предпочитаю проверенное\n"
    "4) Ты скорее:\n"
    "1.Всё планируешь заранее, 2.Делаешь на ходу\n"
    "5) Насколько ты тревожный?\n"
    "1.Часто нервничаю, 2.Почти всегда спокоен\n"
    "6) Что для тебя важнее:\n"
    "1.Семья, традиции, 2.Свобода, приключения\n"
    "7) Ради успеха ты:\n"
    "1.Готов на жертвы, 2.Не гонюсь за победой\n"
    "8) К чужим культурам ты:\n"
    "1.Интересно узнать, 2.Иногда раздражает\n"
    "9) Как общаешься?\n"
    "1.Легко рассказываю, 2.Не делюсь личным\n"
    "10) Что ближе?\n"
    "1.Быть ведущим, 2.Подстраиваться\n"
    "11) Как шутишь?\n"
    "1.С иронией и сарказмом, 2.Осторожно или редко\n"
    "12) Какие у тебя сферы интересов?\n"
    "1.Наука и технологии, 2.Арт, музыка\n"
    "13) Выбери 3 темы:\n"
    "1.Фильмы, 2.Музыка, 3.Книги, 4.Тревел, 5.Бизнес, "
    "6.Психология, 7.Технологии, 8.Спорт, 9.Мода, 10.Осознанность\n"
    "14) Когда ты предпочитаешь общаться?\n"
    "1.Днём, 2.Ночью\n"
    "15) Каким хочешь видеть собеседника?\n"
    "1.Похожим на себя, 2.Противоположным, 3.Главное — интересный\n"
    "Ты — эксперт-психолог и культуролог. Используй:\n"
    "1) Анализы контента соцсетей (ниже «Анализы»)\n"
    "2) Ответы пользователя на опрос (ниже «Опрос»)\n\n"
    "Сформируй JSON-объект user_traits ровно следующей структуры:\n\n"
    "{{\n"
    '  "extraversion": <0-1>,\n'
    '  "agreeableness": <0-1>,\n'
    '  "openness": <0-1>,\n'
    '  "conscientiousness": <0-1>,\n'
    '  "neuroticism": <0-1>,\n'
    '  "empathy": <0-1>,\n'
    '  "aggression_toxicity": <0-1>,\n'
    '  "dominance": <0-1>,\n'
    '  "warmth_affiliation": <0-1>,\n'
    '  "values": {{\n'
    '    "universalism": <0-1>,\n'
    '    "self_direction": <0-1>,\n'
    '    "stimulation": <0-1>,\n'
    '    "achievement": <0-1>,\n'
    '    "power": <0-1>,\n'
    '    "hedonism": <0-1>,\n'
    '    "benevolence": <0-1>,\n'
    '    "tradition": <0-1>,\n'
    '    "conformity": <0-1>,\n'
    '    "security": <0-1>\n'
    '  }},\n'
    '  "interests": {{\n'
    '    "Movies": <0-1>, "Music": <0-1>, "Books": <0-1>, "Travel": <0-1>, "Business": <0-1>,\n'
    '    "Psychology": <0-1>, "Technology": <0-1>, "Sports": <0-1>, "Fashion": <0-1>, "Mindfulness": <0-1>\n'
    '  }},\n'
    '  "languages": ["ru","kz","en"],\n'
    '  "timezone": "Asia/Almaty",\n'
    '  "preferred_format": "text"\n'
    "}}\n\n"
    "Выведи только валидный JSON без пояснений.\n\n"
    "Анализы:\n{analyses}\n\nОпрос:\n{survey}"
)

def _safe_json_loads(raw: str):
    """
    Пытается извлечь JSON-объект из строки, даже если вокруг лишний текст
    или ```json … ```-кодовая ограда.
    """
    raw = raw.strip()

    # убираем ```json … ``` или ``` … ```
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    # пробуем напрямую
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # ищем первую/последнюю фигурные скобки
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            return json.loads(match.group(0))
        raise  # если ничего не помогает — пробрасываем ошибку


# ==================== LOW-LEVEL ANALYSERS ====================
def _gpt_analyze_text(text: str) -> str:
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": ITEM_PROMPT},
                  {"role": "user",   "content": text}]
    )
    return resp.choices[0].message.content.strip()

def _gpt_analyze_image(url: str) -> str:
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ITEM_PROMPT},
            {"role": "user",
             "content": [{"type": "image_url", "image_url": {"url": url}}]}
        ]
    )
    return resp.choices[0].message.content.strip()


def _download(url: str, filename: str = None, tmp_dir: str = None) -> Path:
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    if filename is None:
        filename = Path(url).name.split("?")[0]
    filepath = Path(tmp_dir) / filename

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    filepath.write_bytes(r.content)
    return filepath          # <-- Path, не str

# ==================== TIKTOK SCRAPER ====================
def _analyze_tiktok(username: str, n_reposts: int = 3) -> List[str]:
    run = apify.actor("clockworks/tiktok-scraper").call(run_input={
        "profiles": [username.lstrip("@")],
        "profileScrapeSections": ["reposts"],
        "resultsPerPage": n_reposts,
        "shouldDownloadCovers": True
    })
    ds = apify.dataset(run["defaultDatasetId"])
    analyses = []

    for item in ds.iterate_items():
        caption = item.get("text") or ""
        if caption:
            analyses.append(_gpt_analyze_text(caption))

        cover = (item.get("coversOrigin") or item.get("coversDynamic") or
                 item.get("coversDefault") or item.get("cover"))
        if isinstance(cover, list):
            cover = cover[0]
        if cover:
            analyses.append(_gpt_analyze_image(cover))
    return analyses

# ==================== INSTAGRAM SCRAPER ====================
def _analyze_instagram(username: str, n_posts: int = 3) -> list[str]:
    run = apify.actor("apify/instagram-scraper").call(run_input={
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": n_posts,
        "searchType": "user",
        "addParentData": False,
    })
    ds = apify.dataset(run["defaultDatasetId"])
    analyses = []

    for item in ds.iterate_items():
        caption = item.get("caption") or ""
        if caption:
            analyses.append(_gpt_analyze_text(caption))

        if item.get("displayUrl") and not item.get("isVideo", False):
            img_url  = item["displayUrl"]
            tmp_path = _download(img_url, f"{item['id']}.jpg")   # теперь создаётся корректный путь
            b64      = base64.b64encode(tmp_path.read_bytes()).decode()
            analyses.append(_gpt_analyze_image(f"data:image/jpeg;base64,{b64}"))
    return analyses


# ==================== MAIN ENTRY ====================
def build_user_traits(
    tiktok_username: str | None = None,
    instagram_username: str | None = None,
    survey_answers: dict | None = None,
    n_items: int = 3,
):
    all_analyses = []

    if tiktok_username:
        all_analyses += _analyze_tiktok(tiktok_username, n_items)
    if instagram_username:
        all_analyses += _analyze_instagram(instagram_username, n_items)

    summary_prompt = SUMMARY_PROMPT.format(
        analyses="\n\n".join(all_analyses) or "—",
        survey=json.dumps(survey_answers or {}, ensure_ascii=False, indent=2),
    )

    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Сформируй user_traits."},
            {"role": "user", "content": summary_prompt},
        ],
    )

    # ← безопасно достаём JSON
    return _safe_json_loads(resp.choices[0].message.content)
# ==================== EXAMPLE USAGE ====================
if __name__ == "__main__":
    survey = {
        "q1": 1,
        "q2": 2,
        "q3": 1,
        "q4": 1,                       # если нужен один ответ, иначе сделайте список
        "q5": "часто нервничаю",
        "q6": 2,
        "q7": 1,
        "q8": 1,
        "q9": 1,
        "q10": 1,
        "q11": 1,
        "q12": 1,
        "q13": [1, 2, 3, 5, 7],        # добавили «:» и список
        "q14": "днем",
        "q15": 1
    # остальные ответы добавляйте ниже без комментариев
    }

    traits = build_user_traits(
        tiktok_username   = "aimerkoshmambetov",
        instagram_username= "aimerkoshmambetov",
        survey_answers    = survey,
        n_items           = 3
    )
    print(json.dumps(traits, ensure_ascii=False, indent=2))
