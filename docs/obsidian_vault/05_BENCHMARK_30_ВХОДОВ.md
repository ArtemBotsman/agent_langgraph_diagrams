# Где находятся 30 входных SpecificationReq

Основной файл:

`benchmark/v1_0_synthetic/cases.json`

Подробное человекочитаемое объяснение всех двадцати development cases (кейсов
для разработки): [[11_КАТАЛОГ_20_DEV_КЕЙСОВ]].

`SpecificationReq` (структурированный вход проекта) внутри каждого кейса имеет
ровно шесть полей:

```text
project_task                 (исходная задача пользователя)
project_name                 (название проекта)
project_goal                 (бизнес-цель проекта)
project_description          (описание проекта)
functional_requirements      (список функциональных требований)
non_functional_requirements  (список нефункциональных требований)
```

Рядом находится `manifest.json` (манифест набора), где записаны количество
кейсов, разбиение, происхождение и контрольная сумма.

![[assets/04_benchmark_map.png]]

## Development split (часть для разработки)

Эти 20 кейсов можно использовать при разработке prompts (инструкций модели),
валидаторов и порогов:

1. `B1-DEV-001` — RoomBook.
2. `B1-DEV-002` — Event Signup.
3. `B1-DEV-003` — ParkPass.
4. `B1-DEV-004` — Media Checkout.
5. `B1-DEV-005` — Office Pass.
6. `B1-DEV-006` — Volunteer Roster.
7. `B1-DEV-007` — Clinic Appointment.
8. `B1-DEV-008` — Travel Claims.
9. `B1-DEV-009` — Table Now.
10. `B1-DEV-010` — LabSlot.
11. `B1-DEV-011` — CourseSelect.
12. `B1-DEV-012` — Parcel Track.
13. `B1-DEV-013` — ProcureFlow.
14. `B1-DEV-014` — House Repair.
15. `B1-DEV-015` — Claim Intake.
16. `B1-DEV-016` — Emergency Dispatch.
17. `B1-DEV-017` — FairTrade Disputes.
18. `B1-DEV-018` — Privacy Export.
19. `B1-DEV-019` — City Permit.
20. `B1-DEV-020` — Triage Route.

## Hidden split (отложенная контрольная часть)

Эти 10 кейсов нельзя использовать для настройки после фиксации benchmark
(тестового набора):

1. `B1-HID-001` — Library Desk.
2. `B1-HID-002` — HelpDesk Lite.
3. `B1-HID-003` — Easy Return.
4. `B1-HID-004` — PickFlow.
5. `B1-HID-005` — SubControl.
6. `B1-HID-006` — QuizFlow.
7. `B1-HID-007` — MicroLoan.
8. `B1-HID-008` — Smart Access.
9. `B1-HID-009` — MaintPlan.
10. `B1-HID-010` — FleetCharge.

## Текущий статус фиксации

Набор создан синтетически внутри проекта и прошёл техническую фиксацию автора:

- SHA-256 файла `cases.json`:
  `af8dc532d4d283db43687850213e5795ca227c0d6d054327727462e0ab170917`;
- SHA-256 записи фиксации:
  `c338eadaffaff81db045bd1e9f017f8bc83b78cf6c1715646d7179b18feea111`;
- входы hidden split (скрытой части) отделены от `sealed_hidden_gold.json`
  (закрытых эталонов);
- mutation suite (набор намеренных повреждений) обнаруживает `15/15` заявленных
  классов структурных ошибок.

Это `author-frozen candidate v1.0` (технически зафиксированный автором кандидат),
но ещё не научно утверждённый benchmark. Для окончательного статуса нужны два
эксперта, согласование руководителя и Git tag (метка версии) после согласования.

Подробные метрики и живые результаты: [[14_BASELINE_BENCHMARK_И_LIVE_ЭКСПЕРИМЕНТ]].
