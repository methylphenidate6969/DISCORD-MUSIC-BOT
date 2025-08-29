# 🎵 Discord Music Bot

Jednoduchý Discord bot pro přehrávání hudby z YouTube s podporou playlistů.

## 🚀 Jak spustit

1. **Klonuj repozitář**
   ```bash
   git clone https://github.com/methylphenidate6969/DISCORD-MUSIC-BOT.git
   cd DISCORD-MUSIC-BOT
   ```

2. **Nainstaluj závislosti**
   ```bash
   pip install -r requirements.txt
   ```

3. **Nastav proměnné prostředí**
   - Vytvoř soubor `.env` (nebo uprav existující) a vlož svůj Discord token:
     ```
     DISCORD_TOKEN=tvůj_token
     ```

4. **Spusť bota**
   ```bash
   python main.py
   ```

## 🛠️ Funkce

- `/join` – Připojí bota do hlasového kanálu
- `/leave` – Odpojí bota a vymaže frontu
- `/play <url>` – Přehraje skladbu nebo ji přidá do fronty
- `/stop` – Zastaví přehrávání a vymaže frontu
- `/skip` – Přeskočí aktuální skladbu
- `/create_playlist <název>` – Vytvoří playlist
- `/add_to_playlist <název> <url>` – Přidá skladbu do playlistu (pouze vlastník)
- `/playlist <název> [owner_id]` – Načte playlist a přidá skladby do fronty

## 📁 Playlisty

Playlisty se ukládají do složky `playlists` podle ID uživatele.

## ℹ️ Poznámky

- Bot potřebuje práva pro připojení a mluvení v hlasovém kanálu.
- Pro správné fungování je potřeba mít nainstalovaný `ffmpeg`.

---

Vytvořeno pro Discord komunitu. 🎧
