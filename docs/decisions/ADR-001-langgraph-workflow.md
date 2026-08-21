# ADR-001: LangGraph StateGraph как управляемый workflow

- **Дата:** 2026-08-21
- **Статус:** Accepted

## Контекст
Нужен трассируемый pipeline с LLM и детерминированными проверками, ограниченным repair и воспроизводимостью.

## Решение
Использовать LangGraph Graph API (`StateGraph`, conditional edges, subgraphs as compiled invoke).

## Альтернативы
1. Чистый Python orchestration.
2. Полностью автономные multi-agent frameworks.

## Последствия
+ Явные узлы и маршруты; компиляция; stub DI для тестов.  
− Дополнительная зависимость и boilerplate.
