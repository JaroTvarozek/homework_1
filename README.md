# Agent na počasie 🌤️

Python skript, ktorý zavolá LLM API, nechá model použiť nástroje (tools) a výsledky
nástrojov mu pošle späť, aby dal finálnu odpoveď.

Napíšeš mesto — agent si sám dohľadá súradnice, stiahne predpoveď na najbližšie
3 dni a zhrnie ju do pár viet.

```
$ python homework_1.py "Bratislava"

V Bratislave (Slovensko) nás čakajú tri jasné a suché dni bez zrážok. Vo štvrtok
13. 8. vystúpi teplota na 29 °C, v piatok na 30 °C a v sobotu až na 33,5 °C.
Rána budú výrazne chladnejšie – od 15,7 do 18,7 °C, takže denné výkyvy dosahujú
aj 17 stupňov. Vietor je slabý (do 15 km/h), takže horúčavu nič nezmierni.

Odporúčam ľahké oblečenie, dostatok tekutín a v sobotu sa vyhnúť poobedňajšiemu
slnku; ráno sa však ešte zíde tenká vrstva navyše.
```

## Zadanie a ako ho tento projekt spĺňa

> Napíš Python skript, ktorý zavolá LLM API, použije nástroj a vráti odpoveď späť LLM.

| Požiadavka | Kde v kóde ([homework_1.py](homework_1.py)) |
|---|---|
| Zavolá LLM API | `run_agent()` → `client.messages.create(...)` |
| Použije nástroj | `find_city()`, `get_forecast()` — vykoná ich `run_tool()` |
| Vráti odpoveď späť LLM | blok `tool_result` sa pripojí do `messages` a cyklus pokračuje |

Nástroj nespúšťa skript natvrdo — **rozhoduje sa model**. Skript len vykoná to,
čo si model vypýta, a pošle mu výsledok naspäť.

## Ako to funguje

```
       používateľ: "Bratislava"
              │
              ▼
   ┌─────────────────────────┐
   │ 1. volanie LLM API      │  tools = [find_city, get_forecast]
   └─────────────────────────┘
              │  stop_reason = "tool_use"
              │  → chcem zavolať find_city("Bratislava")
              ▼
   ┌─────────────────────────┐
   │ 2. nástroj vykoná Python│  HTTP GET → Open-Meteo geocoding
   └─────────────────────────┘  → 48.148 / 17.107, Slovensko
              │
              ▼
   ┌─────────────────────────┐
   │ 3. tool_result → späť   │  výsledok sa pripojí do histórie správ
   └─────────────────────────┘
              │
              └──────► späť na krok 1, kým model nepovie, že už má dosť
                              │
                              ▼  stop_reason = "end_turn"
                       finálna odpoveď
```

**Prečo dva nástroje a nie jeden:** model netuší, kde Bratislava leží. Musí
najprv zistiť súradnice (`find_city`) a až potom ich použiť v druhom volaní
(`get_forecast`). Výstup jedného nástroja je vstupom ďalšieho volania — to je
reťazenie nástrojov, teda agent, nie jednorazová funkcia.

## Nástroje

| Nástroj | Čo robí | Zdroj dát |
|---|---|---|
| `find_city(name, count)` | Nájde zemepisné súradnice mesta | [Open-Meteo Geocoding](https://open-meteo.com/en/docs/geocoding-api) |
| `get_forecast(latitude, longitude, days)` | Denná predpoveď: teploty, zrážky, vietor, popis oblohy | [Open-Meteo Forecast](https://open-meteo.com/en/docs) |

Obe API sú verejné a nepotrebujú registráciu ani kľúč — jediný kľúč, ktorý
projekt potrebuje, je ten na LLM.

## Inštalácia

```bash
git clone https://github.com/<tvoj-ucet>/pocasovy-agent.git
cd pocasovy-agent

pip install -r requirements.txt

copy .env.example .env    # Windows;  na Linuxe/macOS: cp .env.example .env
```

Do `.env` doplň svoj kľúč z [console.anthropic.com](https://console.anthropic.com):

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Použitie

```bash
python homework_1.py                               # interaktívny režim (viď nižšie)
python homework_1.py "Bratislava"                  # mesto ako argument
python homework_1.py "Aké bude počasie v Ríme?"    # aj celá otázka
python homework_1.py --verbose "Praha"             # vypíše celý tool-use cyklus
```

### Interaktívny režim

Spustenie bez argumentov (alebo dvojklik na `homework_1.py`) otvorí okno,
ktoré sa pýta na mestá dookola — prázdny riadok ho zavrie:

```
Agent na počasie - tvoj asistent na sledovanie počasia kdekoľvek na svete.
Zadaj mesto a agent preň vyhľadá aktuálnu predpoveď na najbližšie 3 dni
a zhrnie ti ju v pár vetách. Prázdny riadok program ukončí.

Mesto: Kosice

Predpoveď pre Košice na Slovensku. Vo štvrtok 13. 8. bude zamračené, ale suché,
s teplotami od 17 do 27,5 °C a slabým vetrom do 18 km/h. V piatok sa vyjasní –
jasná obloha a až 28,8 °C cez deň. V sobotu bude prevažne jasno a najteplejšie,
do 30 °C. Zrážky sa počas troch dní neočakávajú – hodí sa ľahké oblečenie,
opaľovací krém a dostatok tekutín.

Mesto:
```

### Ukážkový výstup s `--verbose`

Prepínač `--verbose` ukáže každé kolo cyklu — presne vidno, čo model chcel,
čo mu skript vrátil a kedy skončil:

```
$ python homework_1.py --verbose "Bratislava"

-> LLM (round 1)
  <- tool_use: find_city({"name": "Bratislava"})
  -> tool_result: [{"name": "Bratislava", "country": "Slovensko", "admin1":
     "Bratislavský", "latitude": 48.14816, "longitude": 17.10674}, ...]

-> LLM (round 2)
  <- tool_use: get_forecast({"latitude": 48.14816, "longitude": 17.10674})
  -> tool_result: {"days": [{"date": "2026-08-13", "weather": "clear sky",
     "temp_max_c": 29.1, "temp_min_c": 15.7, "precipitation_mm": 0.0,
     "wind_max_kmh": 11.3}, ...]}

-> LLM (round 3)

V Bratislave (Slovensko) nás čakajú tri jasné a suché dni bez zrážok. Vo štvrtok
13. 8. vystúpi teplota na 29 °C, v piatok na 30 °C a v sobotu až na 33,5 °C. ...
```

### Keď je názov mesta nejednoznačný

Geokóder vráti viac miest a model sa opýta — bez toho, aby to bolo kdekoľvek
naprogramované. Interaktívny režim drží jeden súvislý rozhovor a kým agent
čaká na výber, vstupný riadok sa zmení z `Mesto:` na `Odpoveď:`, aby bolo
jasné, že teraz nečaká nové mesto:

```
Mesto: zubak

Našiel som viacero možností:

1. Zubák, Trenčiansky kraj, Slovensko
2. Zubák, Zlínsky kraj, Česko
3. Zubaki, Vicebská oblasť, Bielorusko (55.09, 30.11)
4. Zubaki, Vicebská oblasť, Bielorusko (54.98, 30.61)
5. Zubaki, Smolenská oblasť, Rusko

Zvoľte číslo mesta (1-5):
Odpoveď: 1

Zubák (Trenčiansky kraj, Slovensko) čaká slnečné a postupne teplejšie počasie.
Vo štvrtok 13. 8. bude prevažne jasno, teploty od 11 do 27 °C, v piatok jasno
a až 28 °C, v sobotu vystúpi maximum na 31 °C...

Mesto:
```

## Štruktúra projektu

```
.
├── homework_1.py      # celý agent: schémy nástrojov, ich implementácie, tool-use cyklus
├── requirements.txt   # anthropic, requests, python-dotenv
├── .env.example       # šablóna pre API kľúč
├── .gitignore
└── README.md
```

## Poznámky k návrhu

- **Interaktívny režim je jeden rozhovor.** História správ sa medzi otázkami
  zachováva, takže keď sa model spýta „ktoré mesto myslíte?", odpoveď „1"
  má svoj kontext a funguje. Vstupný riadok sa vtedy prepne na `Odpoveď:`.
- **Chyba nástroja nezhodí program.** Keď je Open-Meteo nedostupné alebo model
  pošle nezmyselný argument, chyba sa pošle modelu späť ako `tool_result`
  s `is_error: true`. Model potom skúsi iný vstup alebo problém vysvetlí
  používateľovi. To je rozdiel medzi agentom a obyčajným skriptom.
- **Popis nástroja riadi model.** V `description` nie je len *čo* nástroj robí,
  ale aj *kedy* ho použiť („Always call this first…", „Never guess the
  weather…"). To ovplyvňuje správanie modelu viac než systémový prompt.
- **Poistka proti zacykleniu.** `MAX_ROUNDS = 8` — keby sa model zacyklil vo
  volaní nástrojov, skript skončí namiesto nekonečného míňania tokenov.
- **WMO kódy prekladám na text.** Open-Meteo vracia počasie ako číslo (`61`);
  preklad na `"light rain"` je pár riadkov a výrazne zlepší odpoveď.
- **Model je konfigurovateľný.** Predvolene `claude-opus-5`, premennou
  `ANTHROPIC_MODEL` v `.env` sa dá prepnúť napr. na lacnejší `claude-haiku-4-5`.

## Použité technológie

- Python 3.12 · [`anthropic`](https://pypi.org/project/anthropic/) ·
  [`requests`](https://pypi.org/project/requests/) ·
  [`python-dotenv`](https://pypi.org/project/python-dotenv/) ·
  [Open-Meteo](https://open-meteo.com)
