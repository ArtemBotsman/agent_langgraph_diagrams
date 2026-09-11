# Источники 2025–2026 и роль каждого источника

Дата фиксации: 09.09.2026. В проект не копируются полные тексты статей: здесь
сохранены постоянные ссылки на первичные страницы публикаций, назначение и
границы применения. Это позволяет восстановить происхождение решений без
нарушения лицензий и без зависимости от случайной поисковой выдачи.

## RE 2026: требования → SysML Activity Diagram

- Источник: [Automated Generation of SysML Activity Diagrams from Industrial Requirements Using LLMs](https://publikationen.bibliothek.kit.edu/1000194327).
- Страница конференции: [IEEE RE 2026](https://conf.researchr.org/details/RE-2026/RE-2026-industrial-innovation-papers/4/Automated-Generation-of-SysML-Activity-Diagrams-from-Industrial-Requirements-Using-LL).
- Для чего используется: обоснование актуальности прямого преобразования
  требований в поведенческие диаграммы; подтверждение необходимости сочетать
  LLM (языковую модель), структурированный pipeline (конвейер) и человеческую
  проверку.
- Ограничение переноса: статья относится к промышленным SysML-моделям и не
  доказывает качество нашего синтетического benchmark (набора тестов).

## 2026 systematic review: LLM и software modeling

- Источник: [Large Language Models for Software Modeling: A Systematic Literature Review](https://arxiv.org/abs/2607.26100).
- Для чего используется: поведенческие диаграммы, consistency (согласованность)
  и quality assurance (контроль качества) исследованы слабее; в работах
  различаются датасеты и метрики; воспроизводимость и hallucination
  (неподтверждённые элементы) остаются проблемами.
- Следствие для проекта: отдельно публикуются benchmark, схемы, логи вызовов,
  формальные проверки, семантические метрики и экспертная оценка.

## ICSE-SEIP 2025: измерения качества диаграмм

- Источник: [A Framework for Evaluating LLM-Generated Sequence Diagrams](https://ieeexplore.ieee.org/document/11121690/).
- Для чего используется: раздельная оценка correctness (корректности),
  completeness (полноты), clarity (ясности) и readability (читаемости).
- Ограничение переноса: предмет статьи — sequence diagrams (диаграммы
  последовательности), поэтому метрики не копируются механически, а служат
  основанием для многомерной оценки.

## R2ABench 2026: требования → архитектура

- Источник: [R2ABench: Benchmarking the Requirements-to-Architecture Capabilities of LLMs](https://arxiv.org/abs/2604.06683).
- Для чего используется: сочетание структурных метрик, многомерной оценки и
  anti-pattern checks (проверок нежелательных шаблонов); сравнение one-shot
  (одного вызова) и agentic (агентного) подхода.
- Следствие: B1 и FULL сравниваются по одинаковому входу и одинаковым
  контрактам, но результат не сводится к одному composite (сводному числу).

## TraceLLM 2026: трассировка требований

- Источник: [TraceLLM: A Benchmark for Requirements Traceability with Large Language Models](https://arxiv.org/abs/2602.01253).
- Для чего используется: разделение наборов, precision/recall/F-score
  (точность/полнота/F-мера) и human review (экспертная проверка) связей.
- Следствие: наши связи оцениваются двусторонне, а hidden test (скрытый тест)
  изолирован от настройки.

## EMSE 2026: LLM в model-driven engineering

- Источник: [Large language models in model-driven engineering: a systematic mapping study](https://link.springer.com/article/10.1007/s10664-026-10921-4).
- Для чего используется: подтверждает распространённость accuracy,
  syntactic/semantic quality, precision/recall/F1 и редкость cost evaluation
  (оценки стоимости).
- Следствие: проект одновременно фиксирует структуру, семантику, трассировку,
  время, токены, стоимость и число исправлений.

## Почему LLM-as-a-judge не является эталоном

- Источник: [GEM 2025: A Critical Evaluation of LLM-as-a-Judge](https://aclanthology.org/2025.gem-1.33/).
- Дополнение: [Position Bias in LLM-as-a-Judge, IJCNLP 2025](https://aclanthology.org/2025.ijcnlp-long.18/).
- Для чего используется: LLM-judge (LLM-судья) чувствителен к модели, prompt
  (инструкции) и позиции ответа, поэтому не заменяет gold (эталон) и двух
  независимых экспертов.

## Технические первичные источники

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) — checkpoint (контрольная точка), thread_id (идентификатор запуска), resume (возобновление).
- [SqliteSaver reference](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver) — локальное сохранение состояния для воспроизводимого прототипа.
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) — явное отключение thinking (режима рассуждения) в измеряемых прогонах.
- [DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/) — OpenAI-compatible (совместимый) контракт вызова.
- [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/?article_id=article_1779470751466_8) — источник диапазона оценки стоимости; в сохранённых прогонах стоимость оставлена `null`, потому что точный тариф не был зафиксирован в окружении.
- [Pyreverse documentation](https://pylint.readthedocs.io/en/latest/additional_tools/pyreverse.html) — локальный смежный baseline (ориентир), который строит class/package diagrams (диаграммы классов/пакетов) из существующего Python-кода.
- [Mermaid flowchart syntax](https://mermaid.js.org/syntax/flowchart.html) — детерминированный формат визуализации после проверки типизированной модели.
- [Groq Qwen 3.8 27B](https://console.groq.com/docs/model/qwen/qwen3.8-27b) — точный model ID, context/output limits, возможности JSON Schema и reasoning.
- [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs) — поддержка strict JSON Schema для `qwen/qwen3.8-27b`.
- [Groq Free Plan rate limits](https://console.groq.com/docs/rate-limits) — RPM/RPD/TPM/TPD для планирования отдельного малого пилота.
