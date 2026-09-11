# Файлы для научного руководителя

Эта страница является единым индексом материалов для согласования. Рабочие
секреты, `.env`, raw prompts/responses и внутренний project context в пакет не
включаются.

## 1. Benchmark и фиксация версии

- [`../../benchmark/v1_0_synthetic/cases.json`](../../benchmark/v1_0_synthetic/cases.json)
  — 30 синтетических кейсов. Каждый кейс содержит шестиполевой
  `SpecificationReq`, split, язык, сложность, gold-акторов, Use Cases,
  milestones, ветвления, покрытие FR, допустимые эквиваленты и запрещённые
  предположения.
- [`../../benchmark/v1_0_synthetic/freeze_record.json`](../../benchmark/v1_0_synthetic/freeze_record.json)
  — контрольная запись версии: SHA-256 файлов, число DEV/hidden, запрет hidden
  tuning и статус внешнего согласования. Она доказывает неизменность набора, но
  не доказывает качество авторской разметки.

## 2. Методика benchmark и метрик

- [`../benchmark/BENCHMARK_AND_METRICS_V0_1.md`](../benchmark/BENCHMARK_AND_METRICS_V0_1.md)
  — состав DEV/hidden, B0/B1/FULL, формулы precision/recall/F1, coverage,
  hallucination, E2E success, latency/tokens/repair, правила интерпретации и
  ограничения автоматической оценки.

## 3. Экспертная рубрика

- [`../../benchmark/expert_review/RUBRIC.md`](../../benchmark/expert_review/RUBRIC.md)
  — единая шкала 1–5 и шесть критериев: правдоподобие домена, границы
  акторов/UC, полнота сценария, ветвления, трассировка и дисциплина
  предположений. Два эксперта должны заполнять формы независимо.
- [`../../benchmark/expert_review/expert_1_blank.csv`](../../benchmark/expert_review/expert_1_blank.csv)
  и [`expert_2_blank.csv`](../../benchmark/expert_review/expert_2_blank.csv) —
  пустые формы. Их нельзя заполнять вместо реальных экспертов.

## 4. Архитектура и трассировка

- [`../architecture/SYSTEM_DESIGN_V0_1.md`](../architecture/SYSTEM_DESIGN_V0_1.md)
  — два агента, корневой оркестратор, вершины/рёбра, контракты, validation и
  bounded repair, а также рассмотренные архитектурные альтернативы.
- [`../architecture/TRACEABILITY_MODEL.md`](../architecture/TRACEABILITY_MODEL.md)
  — правила связей `FR → UC → scenario step → activity node/edge`, стабильные
  ID, origin/rationale и прямые/обратные проверки TraceManifest.

## 5. B0/B1/FULL и первичные результаты

- [`../research/BASELINES_AND_LIVE_EVIDENCE_2026_09_09.md`](../research/BASELINES_AND_LIVE_EVIDENCE_2026_09_09.md)
  — определения baseline, протокол пилота, таблица результатов, корректная
  интерпретация и ограничения вывода.
- [`../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/results.json`](../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/results.json)
  и [`results.csv`](../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/results.csv)
  — первичные машиночитаемые результаты DEV-001, два повтора.

`B0_RULE` — детерминированный нижний ориентир без LLM. `B1_ONESHOT` — один
вызов той же LLM без критики/repair. `FULL` — два LangGraph-агента с формальными
проверками, critic и bounded repair. Pyreverse рассматривается отдельно как
adjacent baseline (смежный ориентир), потому что получает готовый код, а не
требования до кода.

### Дополнение: полный B0 на development split

- [`../research/B0_DEV20_RESULTS_2026_09_09.md`](../research/B0_DEV20_RESULTS_2026_09_09.md)
  — результаты B0 на всех 20 DEV-кейсах, по три повтора: 60/60 технических
  завершений, stability 1.0, semantic composite 0.408 и bootstrap 95% CI
  `[0.356; 0.463]`. Это доказательство воспроизводимости нижнего ориентира, но
  не семантического качества LLM.
- [`../obsidian_vault/assets/13_b0_dev20_quality.png`](../obsidian_vault/assets/13_b0_dev20_quality.png)
  — готовая иллюстрация для обсуждения результатов.
- [`../release/REPRODUCIBILITY_AND_DEMO.md`](../release/REPRODUCIBILITY_AND_DEMO.md)
  — инструкция одного воспроизводимого запуска, состав result bundle и
  демонстрационный сценарий.

Исполняемые внутренние варианты без отдельных компонентов `FULL_NO_CRITIC` и `FULL_NO_REPAIR` уже
подготовлены, но live-результаты по ним пока отсутствуют: запуск требует
отдельного разрешения на платные API-вызовы.

### Дополнение: воспроизводимость и классификация ошибок

- [`../../artifacts/benchmark_runs/b0-dev20-r3-2026-09-09/reproducibility_report.json`](../../artifacts/benchmark_runs/b0-dev20-r3-2026-09-09/reproducibility_report.json)
  — повторный расчёт 60/60 bundles, summary, stability и SHA-256 без LLM.
- [`../../artifacts/benchmark_runs/b0-dev20-r3-2026-09-09/error_analysis.md`](../../artifacts/benchmark_runs/b0-dev20-r3-2026-09-09/error_analysis.md)
  — анализ низкого semantic score и высокого hallucination proxy B0.
- [`../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/reproducibility_report.json`](../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/reproducibility_report.json)
  — проверка всех шести bundles repeated pilot.
- [`../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/error_analysis.md`](../../artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/error_analysis.md)
  — B1 содержит неразрешённые trace failures, FULL обнаруживает и исправляет
  промежуточные дефекты.

## 6. Безопасные конфигурации провайдеров

- [`../../configs/providers/deepseek.env.example`](../../configs/providers/deepseek.env.example)
  — текущий профиль DeepSeek `deepseek-v4-flash`.
- [`../../configs/providers/groq-qwen.env.example`](../../configs/providers/groq-qwen.env.example)
  — кандидат Groq `qwen/qwen3.8-27b` для отдельного robustness pilot.

Файлы показывают API base, model ID, имя переменной ключа и локальные лимиты,
но поле секретного ключа оставлено пустым. Они нужны для воспроизводимости без
риска публикации доступа к API.

## 7. Полученные Activity-диаграммы

- [`../obsidian_vault/assets/07_live_AD-UC001.png`](../obsidian_vault/assets/07_live_AD-UC001.png)
  — просмотр свободных переговорных.
- [`../obsidian_vault/assets/08_live_AD-UC002.png`](../obsidian_vault/assets/08_live_AD-UC002.png)
  — бронирование комнаты с ветвлением «доступно / недоступно».

Это не нарисованные вручную макеты. PNG скомпилированы из Mermaid, который
детерминированно построен из принятой typed Activity-модели live FULL-запуска
RoomBook. Они демонстрируют результат pipeline, но один кейс не доказывает
качество на всём benchmark.

## 8. Итоговый пакет защиты

- [`../final/FINAL_RESEARCH_REPORT.md`](../final/FINAL_RESEARCH_REPORT.md) —
  полный текст итогового отчёта.
- [`../final/DEFENSE_SPEECH_7_MIN.md`](../final/DEFENSE_SPEECH_7_MIN.md) — доклад
  на семь минут.
- [`../final/EXPERIMENT_COMPLETION_PROTOCOL.md`](../final/EXPERIMENT_COMPLETION_PROTOCOL.md)
  — последовательность paid DEV, expert review, scientific freeze и hidden.

Готовые DOCX/PDF, PPTX и обновлённый XLSX перечислены в
[`../obsidian_vault/19_ФИНАЛЬНЫЙ_ПАКЕТ_ОТЧЕТ_ПРЕЗЕНТАЦИЯ_И_ЭКСПЕРИМЕНТ.md`](../obsidian_vault/19_ФИНАЛЬНЫЙ_ПАКЕТ_ОТЧЕТ_ПРЕЗЕНТАЦИЯ_И_ЭКСПЕРИМЕНТ.md).
Эти файлы можно приложить после проверки формулировок. `.env`, ключи и private
raw evidence отправлять нельзя.
