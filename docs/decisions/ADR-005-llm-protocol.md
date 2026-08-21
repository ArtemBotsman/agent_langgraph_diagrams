# ADR-005: Provider-agnostic LLM Protocol

- **Дата:** 2026-08-21
- **Статус:** Accepted

## Решение
`LLMClient` Protocol + `.env.example`; узлы принимают injectable callables. Позже — LiteLLM / OpenAI-compatible.

## Альтернативы
Жёсткая привязка к OpenAI SDK; вызовы внутри узлов без DI.

## Последствия
+ Тесты без сети; смена провайдера без переписывания графа.  
− Реальная интеграция отложена (намеренно на этом этапе).
