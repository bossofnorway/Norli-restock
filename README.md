# Norli Restock Bot

## Kjøre lokalt
```bash
pip install -r requirements.txt
playwright install chromium
python norli_bot.py
```

## Hoste gratis 24/7 på Render.com

1. Push filene til et **privat GitHub-repo**
2. Gå til [render.com](https://render.com) → New → Web Service
3. Koble til GitHub-repoet ditt
4. Sett følgende:
   - **Runtime**: Docker
   - **Instance type**: Free
5. Legg til environment variable:
   - `DISCORD_WEBHOOK` = din webhook-URL
6. I `norli_bot.py`, bytt ut linjen med `DISCORD_WEBHOOK` til:
   ```python
   import os
   DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
   ```
7. Deploy → boten starter og sender oppstartsmelding til Discord

> Render free tier gir 750 timer/mnd. Boten er lett og vil ikke overbruke dette.
