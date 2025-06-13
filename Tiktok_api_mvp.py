import os, requests
from apify_client import ApifyClient
from openai import OpenAI

APIFY_TOKEN       = "apify_api_RAgg1rLfDSMylWYQT2jUotIVsdWVyZ1jRj1P"
OPENAI_API_KEY    = "sk-5XBRs-SSoSScHCXPeRij8JvO_KXHT2mc_Y6n0e7M7qT3BlbkFJvyiweBPGWuzj_fLKGCPw8eKnVN2Scd5gUW7NLaEycA"

client        = ApifyClient(APIFY_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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

def analyze_tiktok_reposts(username: str, n_reposts: int = 3) -> str:
    run_input = {
        "profiles": [username.lstrip("@")],
        "profileScrapeSections": ["reposts"],
        "resultsPerPage": n_reposts,
        "shouldDownloadCovers": True
    }
    run        = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
    dataset_id = run["defaultDatasetId"]
    text_analyses, image_analyses = [], []

    for item in client.dataset(dataset_id).iterate_items():
        caption = item.get("text", "")
        if caption:
            analysis = analyze_text(caption)
            text_analyses.append(analysis)
        cover_url = (item.get("coversOrigin") or item.get("coversDynamic") or
                     item.get("coversDefault") or item.get("cover"))
        if isinstance(cover_url, list):
            cover_url = cover_url[0]
        if cover_url:
            img_analysis = analyze_image(cover_url)
            image_analyses.append(img_analysis)

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
        return summary.choices[0].message.content.strip()
    else:
        return "Нет данных для анализа."


# ==== Example usage ====
if __name__ == "__main__":
    username = "aimerkoshmambetov"
    print(analyze_tiktok_reposts(username, n_reposts=3))
