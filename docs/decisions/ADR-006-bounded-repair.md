# ADR-006: Bounded repair-loop

- **Дата:** 2026-08-21
- **Статус:** Accepted

## Решение
`repair_attempt` / `max_repair_attempts` в State; при ошибках и `attempt < max` → repair; иначе controlled failure node.

## Альтернативы
Бесконечный retry; всегда fail-fast без repair; human-in-the-loop only.

## Последствия
+ Гарантированное завершение; измеримость RQ5.  
− Риск «зациклить» stub repair без реального улучшения (до появления LLM repair).
