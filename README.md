# SOULeMESH — Telegram matching prototype

A Python Telegram bot prototype exploring conversations and matching based on shared interests and profile questionnaires. The repository name retains the earlier spelling `SOULeMASH`.

## Components

- `main.py`: bot flows, profile questionnaires, and matching logic.
- `db.py`: PostgreSQL access using asyncpg.
- `Chatgpt_wrapper.py`: OpenAI and Apify integration for profile analysis.
- `listener.py`: a PostgreSQL notification listener for derived profile data.
- `requirements.txt`: the original dependency list.

## Configuration

Credentials are read from environment variables. Copy `.env.example` to a local `.env` file and fill it with your own values. The application does not automatically load `.env`; export the values in your shell or configure them in your deployment environment.

| Variable | Used for |
| --- | --- |
| `BOT_TOKEN` | Your Telegram bot token |
| `DATABASE_URL` | Your PostgreSQL connection URI |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `APIFY_TOKEN` | Your Apify token for the analysis wrapper |

Missing required values produce a configuration error. `.env` files are ignored by Git.

## Status

This is an earlier prototype, not a complete deployment package. The database schema and deployment configuration need to be established before running it. The listener imports a `DAI_L1` module that is not included, and the Docker startup configuration expects Supervisor, which is not listed in `requirements.txt`.

Historical hardcoded credentials have been removed from the current files. Any previously exposed credentials must be revoked or rotated by their owner; removing them from the latest commit does not remove them from Git history.

No security, privacy, psychological-assessment accuracy, or matching-quality validation is claimed by this repository.
