import os, base64, requests
from apify_client import ApifyClient
from openai import OpenAI

# ========== НАСТРОЙКИ ==========
APIFY_TOKEN       = "apify_api_RAgg1rLfDSMylWYQT2jUotIVsdWVyZ1jRj1P"
TIKTOK_USERNAME   = "aimerkoshmambetov"      # без @ или с @ — не важно
OPENAI_API_KEY    = "sk-5XBRs-SSoSScHCXPeRij8JvO_KXHT2mc_Y6n0e7M7qT3BlbkFJvyiweBPGWuzj_fLKGCPw8eKnVN2Scd5gUW7NLaEycA"

N_REPOSTS_TO_ANALYZE = 3                     # сколько репостов анализировать

# ========== ИНИЦИАЛИЗАЦИЯ ==========
client        = ApifyClient(APIFY_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ========== ПОЛУЧАЕМ РЕПОСТЫ ==========
run_input = {
    "profiles": [TIKTOK_USERNAME.lstrip("@")],
    "profileScrapeSections": ["reposts"],     # важная строчка!
    "resultsPerPage": N_REPOSTS_TO_ANALYZE,
    "shouldDownloadCovers": True              # тянем обложки
}

run         = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
dataset_id  = run["defaultDatasetId"]

# ========== OPENAI ФУНКЦИИ ==========
SYS_PROMPT = (
    "Ты — эксперт-психолог и культуролог. "
    "Проанализируй TikTok-контент по критериям: "
    "Интересы, Тип личности (MBTI/Big Five), Склонность к диалогу, Ценности. "
    "Отвечай структурировано:\n- Интересы\n- Тип личности\n- Склонность к диалогу\n- Ценности"
)

def analyze_text(text: str) -> str:
    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": SYS_PROMPT},
                  {"role": "user",   "content": text}]
    )
    return resp.choices[0].message.content.strip()

def analyze_image(url: str) -> str:
    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user",
             "content": [{"type": "image_url", "image_url": {"url": url}}]}
        ]
    )
    return resp.choices[0].message.content.strip()

# ========== ОБРАБОТКА ==========
text_analyses, image_analyses = [], []

for item in client.dataset(dataset_id).iterate_items():
    print(f"\nВидео: {item.get('webVideoUrl')}")
    # --- текст подписи
    caption = item.get("text", "")
    if caption:
        print("Подпись:", caption)
        analysis = analyze_text(caption)
        print("Анализ текста:\n", analysis)
        text_analyses.append(analysis)

    # --- обложка
    cover_url = (item.get("coversOrigin") or item.get("coversDynamic") or
                 item.get("coversDefault") or item.get("cover"))  # формат может быть списком
    if isinstance(cover_url, list):
        cover_url = cover_url[0]

    if cover_url:
        print("Анализ обложки:")
        img_analysis = analyze_image(cover_url)
        print(img_analysis)
        image_analyses.append(img_analysis)

# ========== СВОДНЫЙ ПОРТРЕТ ==========
if text_analyses or image_analyses:
    summary_prompt = (
        "Вот набор анализов репостов пользователя TikTok. "
        "Составь общий психологический портрет по тем же критериям, "
        "давая краткие аргументы.\n\nАнализы:\n"
        + "\n\n".join(text_analyses + image_analyses)
    )
    summary = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Ты — эксперт-психолог и культуролог."},
                  {"role": "user",   "content": summary_prompt}]
    )
    print("\n==== Финальный портрет пользователя ====\n")
    print(summary.choices[0].message.content.strip())
else:
    print("Нет данных для анализа.")
