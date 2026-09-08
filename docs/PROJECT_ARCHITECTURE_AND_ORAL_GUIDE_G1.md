# Архитектура проекта и шпаргалка для устного отчёта (этап G1)

**Дата:** 2026-08-21  
**Проект:** `Agent/` (пакет `traceable_spec`, Poetry: `agent-nir`)  

**Важно:** это описание факта по коду. `ScriptedLLMClient` — **не** настоящая LLM.

---

## 1. Одной фразой (можно начать с этого)

Собран исследовательский каркас на **LangGraph + Pydantic**: из функциональных требований строится структурированный набор Use Cases и activity-диаграмм с **проверяемой трассировкой** и **ограниченным циклом исправлений (bounded repair)**.  
На этапе G1 Use Case–граф уже гоняется end-to-end через протокол `LLMClient` и **scripted/fake**-клиент; Activity и корневой pipeline на stub-ах; живой платный LLM ещё не подключён.

---

## 2. Зачем это нужно (научная постановка)

Классическая проблема: LLM рисует «красивый» текст или Mermaid, но его трудно **проверить**, **проследить** до требований и **воспроизвести**.

Наш подход:

1. **Источник истины — структурированные модели** (Use Cases, ActivityDiagram), а не свободный текст.
2. **Mermaid — производный вид**: его рисует детерминированная функция из модели, а не LLM напрямую.
3. **Трассировка** хранится явно в `TraceManifest` (ссылки FR→UC, шаг→узел и т.д.).
4. **Проверки двух типов:**
   - детерминированные Python-validators (структура, ID, покрытие FR, целостность ссылок);
   - critic (семантический слой через `LLMClient`; в G1 — scripted/fake).
5. **Bounded repair:** если проверки не прошли — ограниченное число попыток исправить артефакт, иначе контролируемый fail.

Соседний проект `AppFactory-agents` **не** переиспользуется (отдельное решение / независимость НИР).

---

## 3. Что физически лежит в репозитории

| Часть | Назначение |
|-------|------------|
| `src/traceable_spec/entities.py` | Контракты данных (Pydantic) и State графов (TypedDict) |
| `use_cases_graph.py` | Подграф генерации Use Cases |
| `activity_diagram_graph.py` | Подграф activity-модели + Mermaid |
| `graph.py` | Корневой pipeline: Request → GeneratedSpecification |
| `validators/` | Детерминированные проверки |
| `prompts/use_cases.py` | Сборщики промптов UC (generator / critic / repair) |
| `llm/` | Protocol `LLMClient`, парсер JSON, **ScriptedLLMClient (fake)** |
| `mermaid/` | Детерминированный рендер flowchart TD |
| `rendering/` | Человекочитаемый текст UC |
| `evaluation/` | Автоматические метрики (без LLM-as-a-judge) |
| `benchmark/` | Формат кейсов + один development-пример |
| `tests/`, `examples/` | Контрактные и scripted-тесты; demo UC |

---

## 4. Цепочка «как это работает» простыми словами

```text
SpecificationRequest          ← вход: проект + ФТ (+ опц. НФТ) + лимит repair
        ↓
Use Cases graph               ← готовит UC + первичный TraceManifest
        ↓
Activity graph (на каждый UC) ← строит ActivityDiagram, затем Mermaid
        ↓
Проверка трассировки end-to-end
        ↓
Evaluator (автоматические метрики)
        ↓
GeneratedSpecification        ← итоговый артефакт
```

**Фактическая готовность на G1:**

| Звено | Статус |
|-------|--------|
| Вход `SpecificationRequest` | реализован |
| UC-граф на stubs | работает |
| UC-граф на `ScriptedLLMClient` | работает (оркестрация, **не** качество AI) |
| Live LLM adapter | **не реализован** (`PLANNED_NOT_IMPLEMENTED`) |
| Activity-граф | работает на **stubs** + детерминированный Mermaid |
| Activity LLM / prompts | **не реализованы** |
| Корневой pipeline | end-to-end на stubs → `GeneratedSpecification` |
| Latency / tokens / cost | поля-заглушки `None` в evaluator |

---

## 5. Три графа: как объяснить руководителю

Считаем **прикладные вершины** без `START`/`END`. Условные ветви — отдельные переходы.

### 5.1. Use Cases graph — 9 вершин, 9 рёбер (+ START/END → 12)

**Смысл:** из требований получить согласованный набор Use Cases и трассировку.

Поток:

1. **prepare** — скопировать ФТ/НФТ, обнулить счётчик repair.  
2. **generate** — получить структурированный UC-набор (stub или вызов `LLMClient`).  
3. **validate schema** — проверка формы (Pydantic).  
4. **validate deterministic** — жёсткие правила (ID, структура, покрытие FR, FR→UC links).  
5. **criticize** — «умный» разбор (через `LLMClient`; ≠ Python-validator).  
6. **decide** — принять / чинить / сдаться.  
7a. **finalize** — успех.  
7b. **repair** → снова с schema (петля).  
7c. **fail** — контролируемый провал после лимита.

**Фраза для созвона:**  
«UC-граф — это конвейер: сгенерировали → проверили формой → проверили правилами → дали слово critic → либо приняли, либо чиним ограниченное число раз.»

### 5.2. Activity graph — 10 вершин, 10 рёбер (+ START/END → 13)

**Смысл:** для одного Use Case построить activity-модель и **из неё** нарисовать Mermaid.

Отличие от UC: при успехе сначала узел **render_mermaid**, потом finalize.  
Сейчас generate/critic/repair — **stubs** (фиксированный sample), Mermaid — настоящая детерминированная функция.

**Фраза для созвона:**  
«Диаграмму мы не просим у модели текстом: сначала структура ActivityDiagram, потом чистый Python рисует Mermaid. Так результат воспроизводим.»

### 5.3. Root pipeline — 6 вершин, 5 рёбер (+ START/END → 7)

Линейно, без условных ветвей на корне:

1. normalize requirements  
2. run Use Cases subgraph  
3. run Activity subgraph (по каждому UC, сейчас последовательно)  
4. end-to-end trace validation  
5. evaluator  
6. finalize → `GeneratedSpecification`

**Фраза для созвона:**  
«Корень склеивает два подграфа и добавляет сквозную проверку трассировки и автоматические метрики.»

---

## 6. Три «проверщика» — чтобы не путать на защите

| Роль | Кто | Что делает |
|------|-----|------------|
| **Generator** | узел generate (+ `LLMClient`) | Создаёт артефакт (UC или activity) |
| **Deterministic validators** | Python в `validators/` | Одинаковый вход → одинаковый вердикт; структура и трассировка |
| **Critic** | узел criticize (+ `LLMClient`) | Семантический разбор; **не** замена validators |

Repair — отдельный узел: чинит артефакт с учётом списка issues и увеличивает `repair_attempt`.  
Лимит: `repair_attempt < max_repair_attempts` (из запроса, по умолчанию 2), иначе fail.

---

## 7. Трассировка и логи — короткая развилка

- **`TraceManifest`** — продуктовый артефакт: список явных связей между элементами спецификации (FR↔UC, шаг↔узел и т.д.). Это **не** лог выполнения.  
- **Runtime-логи** в классическом смысле (logging/latency/token streams) **почти не реализованы**. Есть учёт вызовов у `ScriptedLLMClient` (`client.calls`) для тестов оркестрации.  
- Метрики **latency_ms / token_usage / cost_usd** в evaluator пока `None` (зарезервированы под live LLM).

---

## 8. Что сказать про «уже сделано» vs «ещё нет»

### Сделано и проверяемо тестами

- Модели и контракты входа/выхода.  
- Три компилируемых LangGraph-графа.  
- Детерминированные validators + Mermaid-renderer.  
- Skeleton evaluator и development-кейс benchmark.  
- G1: промпты UC + wiring `LLMClient` + **ScriptedLLMClient** + сценарии accept / repair / exhaust / bad JSON.  
- Корневой прогон на stubs до `GeneratedSpecification`.

### Ещё нет (честно)

- Реальный LiteLLM / OpenAI-compatible adapter.  
- LLM-узлы и промпты для Activity.  
- Замороженный полный benchmark (~30 кейсов).  
- Полноценные cost/latency эксперименты и ответы на RQ.  
- Git-репозиторий (на момент G1 не инициализирован — отдельное разрешение).

---

## 9. Готовый мини-скрипт на 2–3 минуты

> Мы строим pipeline генерации Use Cases и activity-диаграмм по функциональным требованиям на LangGraph.  
> Главная идея: модель данных и трассировка — источник истины; Mermaid только экспорт.  
> Есть два подграфа и корневой конвейер. В каждом подграфе цикл: генерация → schema → детерминированные проверки → critic → решение: принять, починить или остановиться.  
> Сейчас вертикально доказана оркестрация Use Case–графа на scripted-клиенте: это проверяет граф и контракты, но это не живая модель. Activity и корень пока на stub-ах, но уже сходятся в итоговый `GeneratedSpecification` с метриками-заготовками.  
> Следующий шаг по выбору: live LLM adapter, scripted-срез Activity, или подготовка benchmark freeze.

---

| Вопрос | Файл |
|--------|------|
| Вход/выход и State | `src/traceable_spec/entities.py` |
| UC-граф | `src/traceable_spec/use_cases_graph.py` |
| Activity-граф | `src/traceable_spec/activity_diagram_graph.py` |
| Корень | `src/traceable_spec/graph.py` |
| Validators | `src/traceable_spec/validators/__init__.py` |
| Mermaid | `src/traceable_spec/mermaid/__init__.py` |
| Fake-клиент | `src/traceable_spec/llm/scripted.py` |
| Demo | `examples/run_uc_scripted_pipeline.py` |
| Статус этапа | `docs/project_context/CURRENT_STATUS.md` |

---
