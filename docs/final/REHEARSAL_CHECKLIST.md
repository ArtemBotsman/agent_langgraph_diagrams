# Чек-лист репетиции защиты

## Перед выступлением

- Открыть презентацию и резервный PDF.
- Открыть сохранённый Event Signup B0 result bundle.
- Открыть две Activity PNG и один TraceManifest.
- Не запускать live API во время основной демонстрации.
- Проверить, что `.env`, ключ и private raw evidence не видны на экране.

## Что студент объясняет без подсказки

- шесть полей SpecificationReq;
- почему агентов два;
- чем root orchestrator отличается от агента;
- разницу schema validator, deterministic validator и critic;
- bounded repair и controlled failure;
- цепочку FR - UC - step - activity element;
- B0, B1, FULL и два варианта без отдельных компонентов;
- почему semantic composite не является истиной;
- ограничения одного live-кейса и авторской gold-разметки.

## Резервная демонстрация

1. Показать `examples/event_signup_specification_req.json`.
2. Выполнить B0 через `traceable-spec` в новый каталог.
3. Открыть UC Markdown, stories, Activity Mermaid и quality report.
4. Показать связь activity element с UC step и FR в TraceManifest.
5. Показать сохранённый live FULL PNG вместо сетевого вызова.

## Контроль времени

- Первый прогон: без остановок, зафиксировать длительность каждого слайда.
- Второй прогон: убрать повторения, удержать 6:30-7:00.
- Третий прогон: попросить слушателя задать вопросы из Obsidian note 12.
- Отдельно потренировать ответы о DeepWiki, статическом анализе, метриках,
  hidden test и причине использования LLM.
