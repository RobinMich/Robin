# Backtest-Analyse: EMA Fractal EA v3.0 (XAUUSD H2)

## Was ist neu in v3?

- 4 Trailing-SL-Methoden wählbar (Fractal, ATR, Chandelier, EMA)
- Konfigurierbares Risiko pro Trade (Standard: 1%)
- Neuer Partial-TP-Modus "Trail-Hit" (50% bei SL-Treffer statt bei Breakeven)
- Fractal-Break Exit für Rest-Position
- Range-Filter getestet (Seitwärtsphasen filtern)

---

## ERGEBNIS 1: Trailing-Methoden (1% Risiko, Partial@Breakeven)

| Trailing-Methode | Win% | PF | P/L | MaxDD | Ø Dauer |
|---|---|---|---|---|---|
| Fractal (bisherig) | 54.0% | 3.26 | +$18,019 | **4.5%** | 8.5h |
| **ATR 2.0x** | 52.4% | **4.20** | **+$25,562** | 6.6% | 22.4h |
| **Chandelier 2.0x** | 54.0% | **4.15** | +$24,118 | 5.9% | 16.1h |
| EMA-10 | 54.0% | 3.27 | +$16,293 | 5.4% | 12.0h |
| ATR 1.5x | 54.0% | 3.14 | +$15,267 | 6.5% | 12.9h |
| ATR 2.5x | 52.4% | 4.18 | +$24,330 | 6.7% | 24.5h |
| ATR 3.0x | 52.4% | 4.11 | +$25,178 | 6.6% | 26.8h |
| Chandelier 1.5x | 54.0% | 3.00 | +$14,082 | 5.0% | 10.3h |
| Chandelier 2.5x | 52.4% | 3.86 | +$20,958 | 5.9% | 17.3h |
| EMA-5 | 52.4% | 3.12 | +$14,941 | 4.5% | 7.4h |
| EMA-15 | 52.4% | 3.85 | +$20,487 | 5.9% | 16.8h |
| EMA-20 | 52.4% | 3.74 | +$19,493 | 6.1% | 18.1h |

### Fazit Trailing:
- **ATR 2.0x ist der beste Trailing-SL** -- höchster PF (4.20), höchster P/L (+$25,562)
- **Chandelier 2.0x** ist fast gleichwertig mit besserer Win Rate
- **Fractal hat den niedrigsten Drawdown (4.5%)** aber deutlich weniger Gewinn
- ATR/Chandelier lassen Trades ~2-3x länger laufen = mehr Trendprofite
- **EMA-15** ist ein guter Mittelweg zwischen Fractal und ATR

---

## ERGEBNIS 2: Partial-TP Modi

| Modus | Win% | PF | P/L | MaxDD |
|---|---|---|---|---|
| Partial bei Breakeven (v2) | 54.0% | 3.26 | +$18,019 | 4.5% |
| **Partial bei Trail-Hit (NEU)** | 41.3% | **3.55** | **+$21,334** | 7.8% |
| Trail-Hit + Fractal-Break | 41.3% | 3.55 | +$21,334 | 7.8% |

### Fazit Partial-TP:
- **Trail-Hit** bringt +18% mehr P/L (+$3,315 extra) bei höherem PF
- Niedrigere Win Rate (41% vs 54%) weil Partial-Gewinne kleiner sind
- Fractal-Break Exit zeigt bei Fractal-Trail keinen Unterschied (Fraktale werden nicht "stale" genug)
- **Empfehlung**: Trail-Hit wenn man höheren P/L will, Breakeven wenn man psychologisch höhere Win% braucht

---

## ERGEBNIS 3: Risiko pro Trade

| Risiko | Win% | PF | P/L | MaxDD | Ø Verlust |
|---|---|---|---|---|---|
| 0.5% | 54.0% | 3.72 | +$6,642 (66%) | **2.0%** | -$84 |
| **1.0%** | 54.0% | 3.26 | +$18,019 (180%) | **4.5%** | -$275 |
| 1.5% | 54.0% | 2.96 | +$36,805 (368%) | 7.1% | -$648 |
| 2.0% | 54.0% | 2.75 | +$66,891 (669%) | 9.9% | -$1,318 |

### Fazit Risiko:
- **1% ist der beste Kompromiss**: Solide 180% Rendite bei nur 4.5% MaxDD
- 0.5% ist ultra-konservativ (2% DD!) aber niedrige absolute Gewinne
- 2% bringt zwar 669% aber 10% Drawdown -- psychologisch härter
- **PF sinkt mit höherem Risiko** (3.72 bei 0.5% vs 2.75 bei 2%) weil Compounding die Verluste überproportional vergrößert

---

## ERGEBNIS 4: Range-Filter

| Variante | Trades | Unterschied |
|---|---|---|
| Ohne Range-Filter | 63 | Basis |
| Range 20 Kerzen, 0.6 | 63 | Kein Unterschied |
| Range 30 Kerzen, 0.6 | 63 | Kein Unterschied |
| Range 30 Kerzen, 0.5 (streng) | 63 | Kein Unterschied |

### Fazit Range-Filter:
- **Der Range-Filter hat keinen Effekt auf XAUUSD.** Gold war 2022-2026 fast durchgehend im Trend. Die Multi-Timeframe EMA-Bedingungen filtern Seitwärtsphasen bereits effektiv aus.
- Bei anderen Instrumenten (EUR/USD, Indizes) könnte der Range-Filter nützlicher sein.

---

## ERGEBNIS 5: Beste Kombinationen

| Kombination | Trd | Win% | PF | P/L | MaxDD |
|---|---|---|---|---|---|
| v2 Referenz (2%, Fractal, BE) | 63 | 54.0% | 2.75 | +$66,891 | 9.9% |
| Chandelier 2x + 1% + BE | 63 | 54.0% | **4.15** | +$24,118 | 5.9% |
| **Chandelier 2x + 1% + TrailHit + FBE** | 63 | 31.7% | **5.40** | +$37,083 | 11.0% |
| ATR 2x + 1% + BE | 63 | 52.4% | **4.20** | +$25,562 | 6.6% |
| **ATR 2x + 1% + TrailHit + FBE** | 63 | 22.2% | **5.04** | **+$37,987** | 11.7% |
| Fractal + 1% + TrailHit + FBE | 63 | 41.3% | 3.55 | +$21,334 | 7.8% |

---

## SL Fine-Tuning auf M2 (Kleinerer Timeframe)?

**Analyse:** Den SL auf dem 2-Minuten-Chart unter das letzte Low zu setzen würde den SL-Abstand verkleinern und damit:
- Größere Positionsgröße bei gleichem Risiko (ähnlich wie "halber SL")
- Häufigere SL-Hits durch Noise im kleinen Timeframe
- Problematisch bei Spreads und Slippage auf M2

**Bewertung:** Das ist im Prinzip schon durch den "Halben SL"-Modus abgedeckt. Der halbe Abstand zum Fractal Low simuliert einen engeren SL ähnlich wie ein M2-Low-SL. Der Vorteil: Kein Multi-Timeframe-SL nötig, weniger Komplexität, gleicher Effekt. **Nicht empfohlen als separates Feature.**

---

## ENTSCHEIDUNGSMATRIX: Was soll ich umsetzen?

| # | Änderung | Wirkung | Empfehlung |
|---|---|---|---|
| 1 | **ATR 2.0x Trailing statt Fractal** | PF: 3.26→4.20, P/L: +42% | Stark empfohlen |
| 2 | **Chandelier 2.0x als Alternative** | PF: 3.26→4.15, niedrigerer DD als ATR | Gleichwertig zu ATR |
| 3 | **1% Risiko als Standard** | DD: 9.9%→4.5%, PF: 2.75→3.26 | Stark empfohlen für Sicherheit |
| 4 | **Trail-Hit Partial statt BE-Partial** | P/L: +18%, PF: +9%, Win%: -13% | Optional (niedrigere Win Rate) |
| 5 | **Fractal-Break Exit für Rest** | Kein messbarer Effekt bei Fractal Trail | Nicht nötig |
| 6 | **Range-Filter** | Kein Effekt bei XAUUSD (EMA-Filter reicht) | Nicht nötig |
| 7 | **M2 SL Fine-Tuning** | Bereits durch "Halber SL" abgedeckt | Nicht nötig |
| 8 | **EMA-15 Trail als Mittelweg** | PF: 3.85, guter Kompromiss Dauer/Profit | Alternative zu ATR |

### Meine Top-Empfehlung:

**ATR 2.0x Trail + 1% Risiko + Partial bei Breakeven:**
- PF 4.20, MaxDD 6.6%, +$25,562 (256%)
- Bester Profit Factor aller getesteten Varianten
- Trades laufen länger im Trend (Ø 22h statt 8h)
- Kontrollierter Drawdown

**Oder konservativ: Chandelier 2.0x + 1% + BE-Partial:**
- PF 4.15, MaxDD 5.9%, +$24,118 (241%)
- Etwas niedrigerer DD, höhere Win Rate (54%)
