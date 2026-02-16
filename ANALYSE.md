# Backtest-Analyse: EMA Fractal Expert Advisor (XAUUSD H2)

## Zusammenfassung der Backtest-Ergebnisse

| Variante | Trades | Win% | Profit Factor | Netto P/L | Max DD |
|---|---|---|---|---|---|
| **Standard (SL full, dist 0.5%)** | 70 | 47.1% | **2.71** | +$16,867 (168.7%) | **8.4%** |
| **Halber SL** | 70 | 38.6% | 2.48 | **+$30,627 (306.3%)** | 10.2% |
| Abstandsfilter 1.0% | 91 | 48.4% | 2.47 | +$12,687 (126.9%) | 7.9% |
| Ohne Abstandsfilter | 99 | 48.5% | 2.50 | +$13,217 (132.2%) | 9.2% |
| Max 5 Kerzen | 66 | 45.5% | 2.58 | +$12,866 (128.7%) | 8.4% |

**Zeitraum:** 2022-01-05 bis 2026-02-16 (ca. 4 Jahre XAUUSD)

---

## Bewertung: Ist die Strategie gut?

### Stärken

1. **Hervorragender Profit Factor (2.47–2.71):** Ein PF über 2.0 gilt als sehr stark. Die Strategie hat ein exzellentes Gewinn/Verlust-Verhältnis.

2. **Niedriger Max Drawdown (7.9%–10.2%):** Der maximale Drawdown ist sehr kontrolliert. Unter 15% gilt als professionell.

3. **Konsistente Jahresperformance:** Jedes Jahr positiv (2022–2026), was auf eine robuste Logik hindeutet.

4. **Gute Ø Gewinn/Verlust-Ratio:** Der durchschnittliche Gewinn ist 2–4x höher als der durchschnittliche Verlust.

5. **Breakeven funktioniert:** 50–70% der Trades aktivieren Breakeven, was das Risiko erheblich senkt.

### Schwächen

1. **Win Rate unter 50%:** Die meisten Varianten haben eine Win Rate von 38–48%. Psychologisch anspruchsvoll, da man häufiger verliert als gewinnt.

2. **Wenige Trades (66–99 in 4 Jahren):** Ca. 17–25 Trades/Jahr. Statistische Signifikanz ist begrenzt.

3. **Nur Long-Trades:** Die Strategie nutzt nur bullische Trends. In Bärenmärkten liegt sie brach.

4. **Kurze Haltedauer (6–9 Stunden):** Sehr kurze Trades auf H2 — Slippage und Spread können in der Realität stärker wirken.

---

## Verbesserungsvorschläge

### 1. Halber SL als Standard verwenden
Die "Halber SL"-Variante zeigt die beste Gesamtperformance (+$30,627 / 306%) trotz niedrigerer Win Rate (38.6%). Der engere SL ermöglicht größere Positionsgrößen bei gleichem Risiko, was die Gewinne hebelt.

**Empfehlung:** `sl_mode = "half"` als Standardeinstellung.

### 2. ATR-basierter SL-Filter
Statt eines fixen Abstandsfilters in % könnte ein ATR-basierter Filter den SL dynamisch an die aktuelle Volatilität anpassen.

### 3. Zeitfilter (Session Filter)
Trades nur während der London/NY Sessions (08:00–20:00 UTC) ausführen, da Gold in diesen Zeiten die stärksten Trends zeigt.

### 4. Short-Variante hinzufügen
Umgekehrte Bedingungen für Short-Trades (W: EMA10 < EMA20, etc.) würden die Handelshäufigkeit verdoppeln und Bärenmärkte nutzen.

### 5. Pyramiding / Nachkauf
Bei starken Trends (mehrere aufeinanderfolgende Fractal-Durchbrüche) könnte man die Position vergrößern.

### 6. Partielles Gewinnmitnehmen
50% der Position beim ersten Fractal-Durchbruch (Breakeven-Punkt) schließen, den Rest mit Trailing SL laufen lassen.

---

## Empfohlene Konfiguration

Basierend auf den Backtest-Ergebnissen:

| Parameter | Wert | Begründung |
|---|---|---|
| SL Modus | **Halber Abstand** | Beste Gesamtperformance |
| Abstandsfilter | **0.5%** | Bester Profit Factor |
| Max Kerzen | **10** | Guter Kompromiss zwischen Trades und Qualität |
| Breakeven | **Ja** | Senkt Drawdown signifikant |
| Risiko/Trade | **2%** | Konservativ bei DD < 10% |
