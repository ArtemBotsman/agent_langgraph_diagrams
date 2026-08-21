# ADR-002: TypedDict State + Pydantic contracts

- **Дата:** 2026-08-21
- **Статус:** Accepted

## Контекст
Нужны и производительный State LangGraph, и жёсткие внешние контракты.

## Решение
TypedDict для внутреннего State; Pydantic v2 (`extra="forbid"`) для SpecificationRequest, доменных сущностей, отчётов.

## Альтернативы
Только Pydantic State; только dict.

## Последствия
+ Соответствует рекомендациям Graph API; строгая валидация на границах.  
− Нужна дисциплина синхронизации полей State и моделей.
