"""Build the 30-case synthetic benchmark candidate used by the NIR project.

The generated benchmark is intentionally labelled as synthetic and unreviewed.
It is a technically complete candidate for supervisor/expert review, not a
replacement for the promised external benchmark cases.
"""

# The corpus keeps natural-language requirements as inspectable source strings.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "benchmark" / "v1_0_synthetic"
CASES_PATH = OUTPUT_DIR / "cases.json"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


def gold_uc(
    name: str,
    actor: str,
    fr_numbers: list[int],
    milestones: list[str],
    *,
    branches: list[dict[str, Any]] | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "name_aliases": aliases or [],
        "primary_actor": actor,
        "source_fr_numbers": fr_numbers,
        "required_milestones": milestones,
        "required_branches": branches or [],
    }


def branch(condition: str, *outcomes: str) -> dict[str, Any]:
    return {"condition": condition, "required_outcomes": list(outcomes)}


def benchmark_case(
    *,
    title: str,
    language: str,
    complexity: str,
    task: str,
    project_name: str,
    goal: str,
    description: str,
    frs: list[str],
    nfrs: list[str],
    actors: dict[str, list[str]],
    use_cases: list[dict[str, Any]],
    ambiguity: str = "none",
    forbidden_assumptions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "language": language,
        "complexity": complexity,
        "specification_req": {
            "project_task": task,
            "project_name": project_name,
            "project_goal": goal,
            "project_description": description,
            "functional_requirements": frs,
            "non_functional_requirements": nfrs,
        },
        "gold": {
            "review_status": "synthetic_author_draft",
            "actor_slots": [
                {"slot_id": f"ACTOR-{idx:03d}", "canonical": name, "any_of": aliases}
                for idx, (name, aliases) in enumerate(actors.items(), start=1)
            ],
            "use_case_slots": use_cases,
            "fr_coverage": {f"FR-{idx:03d}": "covered" for idx in range(1, len(frs) + 1)},
            "nfr_expectations": [
                {"nfr_id": f"NFR-{idx:03d}", "must_be_preserved": True}
                for idx in range(1, len(nfrs) + 1)
            ],
            "known_ambiguity": ambiguity,
            "forbidden_assumptions": forbidden_assumptions or [],
            "equivalence_policy": {
                "allow_renaming": True,
                "allow_uc_split_merge": True,
                "allow_linear_node_split_merge": True,
                "allow_additional_supported_detail": True,
                "require_same_actor_goal_milestone_branch_semantics": True,
                "pixel_layout_ignored": True,
            },
        },
    }


CASE_CANDIDATES: list[dict[str, Any]] = [
    benchmark_case(
        title="Бронирование переговорной",
        language="ru",
        complexity="simple",
        task="Создать сервис бронирования переговорных комнат.",
        project_name="RoomBook",
        goal="Снизить число конфликтов при бронировании комнат.",
        description="Сотрудник выбирает свободную переговорную и резервирует временной слот.",
        frs=[
            "Сотрудник просматривает свободные комнаты на выбранное время.",
            "Сотрудник бронирует свободную комнату.",
            "Система отклоняет пересекающееся бронирование.",
        ],
        nfrs=["Подтверждение бронирования должно занимать не более 2 секунд."],
        actors={"Сотрудник": ["работник", "пользователь"], "Система бронирования": ["сервис"]},
        use_cases=[
            gold_uc(
                "Забронировать переговорную",
                "Сотрудник",
                [1, 2, 3],
                ["выбрать время", "найти свободную комнату", "подтвердить бронирование"],
                branches=[
                    branch(
                        "слот уже занят", "отклонить бронирование", "предложить выбрать другой слот"
                    )
                ],
            )
        ],
    ),
    benchmark_case(
        title="Регистрация на мероприятие",
        language="ru",
        complexity="simple",
        task="Создать приложение регистрации участников мероприятия.",
        project_name="Event Signup",
        goal="Собирать подтвержденные регистрации без ручного ввода организатором.",
        description="Посетитель просматривает мероприятие, заполняет форму и получает подтверждение.",
        frs=[
            "Посетитель просматривает описание мероприятия.",
            "Посетитель отправляет имя и email для регистрации.",
            "Система не допускает повторную регистрацию одного email.",
        ],
        nfrs=[
            "Интерфейс должен быть доступен на русском языке.",
            "Email не должен попадать в журналы приложения в открытом виде.",
        ],
        actors={"Посетитель": ["участник", "гость"], "Организатор": ["администратор мероприятия"]},
        use_cases=[
            gold_uc(
                "Зарегистрироваться на мероприятие",
                "Посетитель",
                [1, 2, 3],
                [
                    "просмотреть мероприятие",
                    "ввести регистрационные данные",
                    "получить подтверждение",
                ],
                branches=[
                    branch("email уже зарегистрирован", "показать отказ без создания дубликата")
                ],
            )
        ],
    ),
    benchmark_case(
        title="Поиск книги в библиотеке",
        language="ru",
        complexity="simple",
        task="Создать каталог библиотеки с поиском и выдачей книг.",
        project_name="Library Desk",
        goal="Упростить читателю поиск и получение доступной книги.",
        description="Читатель ищет книгу по названию и оформляет выдачу доступного экземпляра.",
        frs=[
            "Читатель ищет книгу по названию.",
            "Система показывает доступность экземпляров.",
            "Библиотекарь оформляет выдачу доступного экземпляра.",
        ],
        nfrs=["Поиск должен возвращать ответ не более чем за 3 секунды."],
        actors={"Читатель": ["посетитель библиотеки"], "Библиотекарь": ["оператор выдачи"]},
        use_cases=[
            gold_uc(
                "Найти и получить книгу",
                "Читатель",
                [1, 2, 3],
                ["ввести название", "увидеть доступность", "запросить выдачу", "оформить выдачу"],
                branches=[branch("экземпляр недоступен", "сообщить о недоступности")],
            )
        ],
    ),
    benchmark_case(
        title="Visitor parking permit",
        language="en",
        complexity="simple",
        task="Build a visitor parking permit request service.",
        project_name="ParkPass",
        goal="Issue time-limited visitor permits without a paper form.",
        description="A resident requests a permit for a visitor vehicle and security verifies it.",
        frs=[
            "A resident submits the visitor vehicle plate and visit time.",
            "The system issues a permit when the request is complete.",
            "Security can verify an active permit by plate number.",
        ],
        nfrs=["Permit lookup must complete within two seconds."],
        actors={"Resident": ["tenant"], "Security officer": ["guard"]},
        use_cases=[
            gold_uc(
                "Request visitor permit",
                "Resident",
                [1, 2],
                ["enter plate and visit time", "validate required data", "issue permit"],
            ),
            gold_uc(
                "Verify visitor permit",
                "Security officer",
                [3],
                ["enter plate", "show active permit status"],
            ),
        ],
    ),
    benchmark_case(
        title="Equipment checkout",
        language="en",
        complexity="simple",
        task="Create an equipment checkout application for a media lab.",
        project_name="Media Checkout",
        goal="Track who has borrowed each device.",
        description="Students request available equipment and staff record checkout and return.",
        frs=[
            "A student requests an available device.",
            "A lab assistant records the checkout.",
            "A lab assistant records the return and device condition.",
        ],
        nfrs=["Every checkout and return must be auditable."],
        actors={"Student": ["borrower"], "Lab assistant": ["staff member"]},
        use_cases=[
            gold_uc(
                "Check out equipment",
                "Student",
                [1, 2],
                ["select available device", "approve request", "record borrower and due time"],
            ),
            gold_uc(
                "Return equipment",
                "Lab assistant",
                [3],
                ["identify checkout", "record return", "record condition"],
            ),
        ],
    ),
    benchmark_case(
        title="Заказ пропуска",
        language="ru",
        complexity="simple",
        task="Создать сервис заказа временного пропуска в офис.",
        project_name="Office Pass",
        goal="Сократить время оформления посетителей.",
        description="Сотрудник приглашает посетителя, а администратор подтверждает выдачу пропуска.",
        frs=[
            "Сотрудник создаёт приглашение с ФИО и временем визита.",
            "Администратор подтверждает или отклоняет приглашение.",
            "Посетителю отправляется итоговый статус.",
        ],
        nfrs=["Персональные данные должны храниться не дольше 30 дней после визита."],
        actors={
            "Сотрудник": ["приглашающий"],
            "Администратор": ["оператор пропусков"],
            "Посетитель": ["гость"],
        },
        use_cases=[
            gold_uc(
                "Оформить временный пропуск",
                "Сотрудник",
                [1, 2, 3],
                [
                    "создать приглашение",
                    "проверить приглашение",
                    "зафиксировать решение",
                    "уведомить посетителя",
                ],
                branches=[
                    branch(
                        "приглашение отклонено", "сохранить отказ", "уведомить посетителя об отказе"
                    )
                ],
            )
        ],
    ),
    benchmark_case(
        title="Simple helpdesk ticket",
        language="en",
        complexity="simple",
        task="Build a small internal helpdesk ticket system.",
        project_name="HelpDesk Lite",
        goal="Ensure employee incidents are assigned and tracked.",
        description="An employee reports an issue and a support agent resolves it.",
        frs=[
            "An employee creates a ticket with a category and description.",
            "The system assigns the ticket to a support queue.",
            "A support agent resolves the ticket and records a resolution.",
        ],
        nfrs=["Ticket changes must be recorded in an immutable audit history."],
        actors={"Employee": ["requester"], "Support agent": ["technician"]},
        use_cases=[
            gold_uc(
                "Submit support ticket",
                "Employee",
                [1, 2],
                ["enter issue", "classify issue", "assign support queue"],
            ),
            gold_uc(
                "Resolve support ticket",
                "Support agent",
                [3],
                ["open assigned ticket", "record resolution", "close ticket"],
            ),
        ],
    ),
    benchmark_case(
        title="Volunteer shift signup",
        language="en",
        complexity="simple",
        task="Create a volunteer shift signup page.",
        project_name="Volunteer Roster",
        goal="Fill volunteer shifts without overbooking.",
        description="Volunteers select a shift with remaining capacity and receive confirmation.",
        frs=[
            "A volunteer views shifts with remaining capacity.",
            "A volunteer signs up for one shift.",
            "The system rejects signup when the shift is full.",
        ],
        nfrs=["The signup page must work on a mobile viewport."],
        actors={"Volunteer": ["participant"], "Coordinator": ["organizer"]},
        use_cases=[
            gold_uc(
                "Sign up for a shift",
                "Volunteer",
                [1, 2, 3],
                [
                    "view available shifts",
                    "select shift",
                    "reserve capacity",
                    "receive confirmation",
                ],
                branches=[branch("shift is full", "reject signup", "keep capacity unchanged")],
            )
        ],
    ),
    benchmark_case(
        title="Запись в поликлинику",
        language="ru",
        complexity="medium",
        task="Создать сервис самостоятельной записи пациента к врачу.",
        project_name="Clinic Appointment",
        goal="Сократить нагрузку на регистратуру.",
        description="Пациент выбирает специальность, врача и свободное время, затем может отменить запись.",
        frs=[
            "Пациент выбирает медицинскую специальность.",
            "Система показывает врачей и свободные слоты.",
            "Пациент подтверждает запись.",
            "Система запрещает двойное бронирование слота.",
            "Пациент отменяет будущую запись.",
        ],
        nfrs=[
            "Медицинские данные должны быть доступны только авторизованному пациенту.",
            "Подтверждение записи должно занимать не более 3 секунд.",
        ],
        actors={"Пациент": ["пользователь"], "Врач": ["специалист"]},
        use_cases=[
            gold_uc(
                "Записаться к врачу",
                "Пациент",
                [1, 2, 3, 4],
                [
                    "выбрать специальность",
                    "выбрать врача и слот",
                    "проверить актуальность слота",
                    "создать запись",
                ],
                branches=[
                    branch("слот занят", "не создавать запись", "предложить обновить список слотов")
                ],
            ),
            gold_uc(
                "Отменить запись",
                "Пациент",
                [5],
                ["выбрать будущую запись", "подтвердить отмену", "освободить слот"],
            ),
        ],
    ),
    benchmark_case(
        title="Возврат интернет-заказа",
        language="ru",
        complexity="medium",
        task="Создать процесс оформления возврата товара интернет-магазина.",
        project_name="Easy Return",
        goal="Автоматизировать согласование допустимых возвратов.",
        description="Покупатель выбирает заказ, причину и способ возврата, система проверяет срок и статус товара.",
        frs=[
            "Покупатель выбирает полученный заказ и товар.",
            "Покупатель указывает причину возврата.",
            "Система проверяет срок возврата.",
            "Система формирует этикетку для допустимого возврата.",
            "Сотрудник склада подтверждает получение товара.",
        ],
        nfrs=["История возврата должна сохраняться для аудита не менее года."],
        actors={"Покупатель": ["клиент"], "Сотрудник склада": ["кладовщик"]},
        use_cases=[
            gold_uc(
                "Оформить возврат",
                "Покупатель",
                [1, 2, 3, 4],
                [
                    "выбрать товар",
                    "указать причину",
                    "проверить срок",
                    "создать возврат",
                    "получить этикетку",
                ],
                branches=[
                    branch(
                        "срок возврата истёк",
                        "отказать в автоматическом возврате",
                        "показать причину отказа",
                    )
                ],
            ),
            gold_uc(
                "Принять возвращённый товар",
                "Сотрудник склада",
                [5],
                ["найти возврат", "зафиксировать получение", "обновить статус возврата"],
            ),
        ],
    ),
    benchmark_case(
        title="Travel expense approval",
        language="en",
        complexity="medium",
        task="Build a travel expense submission and approval workflow.",
        project_name="Travel Claims",
        goal="Reduce manual checking of employee expense claims.",
        description="An employee submits receipts; a manager reviews policy exceptions and finance reimburses approved claims.",
        frs=[
            "An employee creates an expense claim with trip details.",
            "The employee attaches receipts to expense items.",
            "The system flags items above policy limits.",
            "A manager approves or rejects the claim.",
            "Finance records reimbursement for an approved claim.",
        ],
        nfrs=[
            "Receipt files must be encrypted at rest.",
            "All approval decisions must be auditable.",
        ],
        actors={
            "Employee": ["claimant"],
            "Manager": ["approver"],
            "Finance specialist": ["accountant"],
        },
        use_cases=[
            gold_uc(
                "Submit travel claim",
                "Employee",
                [1, 2, 3],
                [
                    "enter trip details",
                    "add expense items",
                    "attach receipts",
                    "check policy limits",
                    "submit claim",
                ],
                branches=[branch("item exceeds policy limit", "flag policy exception")],
            ),
            gold_uc(
                "Review travel claim",
                "Manager",
                [4],
                ["inspect claim and flags", "record approval decision"],
                branches=[branch("claim rejected", "record rejection reason", "notify employee")],
            ),
            gold_uc(
                "Record reimbursement",
                "Finance specialist",
                [5],
                ["select approved claim", "record reimbursement", "mark claim paid"],
            ),
        ],
    ),
    benchmark_case(
        title="Restaurant reservation",
        language="en",
        complexity="medium",
        task="Create a restaurant table reservation service.",
        project_name="Table Now",
        goal="Accept reservations while respecting table capacity.",
        description="A guest requests a table; staff can confirm, modify, or cancel reservations.",
        frs=[
            "A guest searches available times for party size and date.",
            "A guest submits contact details to reserve a table.",
            "The system prevents reservations above available capacity.",
            "Staff can modify an existing reservation.",
            "Staff can cancel an existing reservation.",
        ],
        nfrs=["Contact details must not be displayed to unauthorized staff roles."],
        actors={"Guest": ["customer"], "Host": ["restaurant staff"]},
        use_cases=[
            gold_uc(
                "Reserve a table",
                "Guest",
                [1, 2, 3],
                [
                    "enter date and party size",
                    "show available times",
                    "enter contact details",
                    "check capacity",
                    "confirm reservation",
                ],
                branches=[
                    branch("capacity unavailable", "reject requested time", "offer available times")
                ],
            ),
            gold_uc(
                "Manage reservation",
                "Host",
                [4, 5],
                ["find reservation", "modify or cancel reservation", "save new status"],
            ),
        ],
    ),
    benchmark_case(
        title="Warehouse picking",
        language="en",
        complexity="medium",
        task="Build a warehouse picking task application.",
        project_name="PickFlow",
        goal="Guide pickers and record stock discrepancies.",
        description="A picker receives an ordered route, scans items, and reports shortages.",
        frs=[
            "A picker receives an assigned pick list.",
            "The system orders stops by warehouse location.",
            "The picker scans each picked item.",
            "The system rejects an unexpected item scan.",
            "The picker records a stock shortage.",
        ],
        nfrs=[
            "The mobile workflow must tolerate a temporary network loss.",
            "Every stock change must be auditable.",
        ],
        actors={"Picker": ["warehouse worker"], "Inventory supervisor": ["supervisor"]},
        use_cases=[
            gold_uc(
                "Complete pick list",
                "Picker",
                [1, 2, 3, 4, 5],
                [
                    "open assigned list",
                    "follow ordered stops",
                    "scan expected item",
                    "record picked quantity",
                    "complete list",
                ],
                branches=[
                    branch("unexpected item scanned", "reject scan", "keep task unchanged"),
                    branch("stock is insufficient", "record shortage", "continue remaining items"),
                ],
            )
        ],
    ),
    benchmark_case(
        title="Запись на лабораторное оборудование",
        language="ru",
        complexity="medium",
        task="Создать сервис резервирования лабораторного оборудования.",
        project_name="LabSlot",
        goal="Исключить пересечения и неподготовленные запуски оборудования.",
        description="Исследователь резервирует установку, указывает проект и подтверждает наличие обучения по безопасности.",
        frs=[
            "Исследователь просматривает доступность установки.",
            "Исследователь указывает проект и временной интервал.",
            "Система проверяет действующее обучение по безопасности.",
            "Ответственный сотрудник одобряет заявки на особо опасное оборудование.",
            "Система отменяет неподтвержденную заявку после истечения срока.",
        ],
        nfrs=["Журнал бронирований и одобрений должен храниться пять лет."],
        actors={
            "Исследователь": ["пользователь оборудования"],
            "Ответственный сотрудник": ["лаборант", "владелец установки"],
        },
        use_cases=[
            gold_uc(
                "Запросить оборудование",
                "Исследователь",
                [1, 2, 3, 4, 5],
                [
                    "выбрать установку и время",
                    "указать проект",
                    "проверить обучение",
                    "создать заявку",
                    "получить решение",
                ],
                branches=[
                    branch("обучение недействительно", "отклонить заявку"),
                    branch(
                        "требуется одобрение", "направить ответственному", "зафиксировать решение"
                    ),
                    branch("срок подтверждения истёк", "отменить заявку"),
                ],
            )
        ],
    ),
    benchmark_case(
        title="University course registration",
        language="en",
        complexity="medium",
        task="Build a university course registration portal.",
        project_name="CourseSelect",
        goal="Let students enroll while enforcing prerequisites and capacity.",
        description="Students search courses, enroll or join a waitlist, and drop future courses.",
        frs=[
            "A student searches courses by term and subject.",
            "The system checks course prerequisites.",
            "The system checks remaining capacity.",
            "A student enrolls in an eligible course.",
            "A student joins a waitlist when a course is full.",
            "A student drops a future course.",
        ],
        nfrs=["Enrollment updates must be serializable to prevent oversubscription."],
        actors={"Student": ["learner"], "Registrar": ["academic administrator"]},
        use_cases=[
            gold_uc(
                "Enroll in course",
                "Student",
                [1, 2, 3, 4, 5],
                ["search course", "check prerequisites", "check capacity", "enroll student"],
                branches=[
                    branch(
                        "prerequisite missing", "reject enrollment", "show missing prerequisite"
                    ),
                    branch("course full", "offer waitlist", "record waitlist position"),
                ],
            ),
            gold_uc(
                "Drop course", "Student", [6], ["select enrollment", "confirm drop", "release seat"]
            ),
        ],
    ),
    benchmark_case(
        title="Подписка и оплата",
        language="ru",
        complexity="medium",
        task="Создать управление подпиской цифрового сервиса.",
        project_name="SubControl",
        goal="Автоматизировать подключение, продление и отмену подписки.",
        description="Клиент выбирает тариф, оплачивает подписку, меняет тариф или отключает автопродление.",
        frs=[
            "Клиент выбирает доступный тариф.",
            "Система создаёт платёж через внешний платёжный сервис.",
            "Система активирует подписку после подтверждения оплаты.",
            "Клиент меняет тариф со следующего расчётного периода.",
            "Клиент отключает автопродление.",
        ],
        nfrs=[
            "Данные банковской карты не должны сохраняться приложением.",
            "Повторный callback оплаты не должен создавать вторую подписку.",
        ],
        actors={"Клиент": ["подписчик"], "Платёжный сервис": ["платёжный провайдер"]},
        use_cases=[
            gold_uc(
                "Оформить подписку",
                "Клиент",
                [1, 2, 3],
                [
                    "выбрать тариф",
                    "создать платёж",
                    "получить подтверждение оплаты",
                    "активировать подписку",
                ],
                branches=[
                    branch("оплата отклонена", "не активировать подписку", "показать статус оплаты")
                ],
            ),
            gold_uc(
                "Изменить подписку",
                "Клиент",
                [4, 5],
                [
                    "выбрать изменение",
                    "зафиксировать новый тариф или отключение продления",
                    "показать дату вступления изменения",
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Parcel delivery tracking",
        language="en",
        complexity="medium",
        task="Create a parcel tracking and delivery confirmation service.",
        project_name="Parcel Track",
        goal="Give senders and recipients a reliable parcel status.",
        description="Carrier events update parcel status; the recipient confirms delivery or reports a problem.",
        frs=[
            "A sender creates a shipment with recipient details.",
            "A carrier posts parcel scan events.",
            "The system derives the current parcel status from accepted events.",
            "A recipient views the current status.",
            "A recipient confirms delivery or reports damage.",
        ],
        nfrs=[
            "Duplicate carrier events must be idempotent.",
            "Tracking history must be retained for one year.",
        ],
        actors={"Sender": ["shipper"], "Carrier": ["delivery provider"], "Recipient": ["receiver"]},
        use_cases=[
            gold_uc(
                "Create shipment",
                "Sender",
                [1],
                ["enter recipient details", "create tracking identifier"],
            ),
            gold_uc(
                "Update tracking status",
                "Carrier",
                [2, 3],
                ["receive scan event", "deduplicate event", "derive current status"],
            ),
            gold_uc(
                "Review delivery",
                "Recipient",
                [4, 5],
                ["view tracking status", "confirm delivery or report damage"],
                branches=[branch("parcel damaged", "record damage report")],
            ),
        ],
    ),
    benchmark_case(
        title="Согласование заявки на закупку",
        language="ru",
        complexity="medium",
        task="Создать workflow заявки на закупку.",
        project_name="ProcureFlow",
        goal="Контролировать бюджет и согласования до заказа товара.",
        description="Инициатор создаёт заявку, система проверяет бюджет, руководитель и закупщик принимают решения.",
        frs=[
            "Инициатор добавляет позиции и обоснование закупки.",
            "Система проверяет доступный бюджет подразделения.",
            "Руководитель согласует или отклоняет заявку.",
            "Закупщик выбирает поставщика для согласованной заявки.",
            "Инициатор видит историю решений.",
        ],
        nfrs=["Все решения должны иметь автора и временную метку."],
        actors={
            "Инициатор": ["заказчик"],
            "Руководитель": ["менеджер"],
            "Закупщик": ["специалист по закупкам"],
        },
        use_cases=[
            gold_uc(
                "Подать заявку на закупку",
                "Инициатор",
                [1, 2],
                ["добавить позиции", "указать обоснование", "проверить бюджет", "отправить заявку"],
                branches=[branch("бюджет недостаточен", "остановить отправку", "показать дефицит")],
            ),
            gold_uc(
                "Согласовать заявку",
                "Руководитель",
                [3, 5],
                [
                    "просмотреть заявку",
                    "принять решение",
                    "зафиксировать автора и время",
                    "показать решение инициатору",
                ],
            ),
            gold_uc(
                "Выбрать поставщика",
                "Закупщик",
                [4],
                ["открыть согласованную заявку", "зафиксировать выбранного поставщика"],
            ),
        ],
    ),
    benchmark_case(
        title="Online quiz attempt",
        language="en",
        complexity="medium",
        task="Build a timed quiz attempt workflow for a learning platform.",
        project_name="QuizFlow",
        goal="Grade objective quizzes consistently and preserve attempt history.",
        description="A learner starts a timed quiz, saves answers, submits, and receives an automatic score.",
        frs=[
            "A learner starts an available quiz attempt.",
            "The system records the attempt start time.",
            "The learner saves answers before the deadline.",
            "The system automatically submits when time expires.",
            "The system calculates an objective score.",
            "The learner views the final score.",
        ],
        nfrs=["A temporary connection loss must not erase previously saved answers."],
        actors={"Learner": ["student"], "Instructor": ["teacher"]},
        use_cases=[
            gold_uc(
                "Complete quiz attempt",
                "Learner",
                [1, 2, 3, 4, 5, 6],
                [
                    "start attempt",
                    "record deadline",
                    "save answers",
                    "submit attempt",
                    "calculate score",
                    "show final score",
                ],
                branches=[
                    branch(
                        "time expires",
                        "submit current answers automatically",
                        "prevent later changes",
                    )
                ],
            )
        ],
    ),
    benchmark_case(
        title="Заявка на ремонт дома",
        language="ru",
        complexity="medium",
        task="Создать сервис заявок жильцов на ремонт общедомового имущества.",
        project_name="House Repair",
        goal="Прозрачно назначать и закрывать ремонтные работы.",
        description="Житель сообщает проблему, диспетчер назначает исполнителя, исполнитель прикладывает результат.",
        frs=[
            "Житель создаёт заявку с адресом, категорией и описанием.",
            "Житель прикладывает фотографию проблемы.",
            "Диспетчер назначает исполнителя и срок.",
            "Исполнитель меняет статус и прикладывает фотографию результата.",
            "Житель подтверждает решение или переоткрывает заявку.",
        ],
        nfrs=["Фотографии должны быть доступны только участникам заявки."],
        actors={"Житель": ["заявитель"], "Диспетчер": ["оператор"], "Исполнитель": ["мастер"]},
        use_cases=[
            gold_uc(
                "Создать заявку на ремонт",
                "Житель",
                [1, 2],
                ["указать адрес и проблему", "прикрепить фотографию", "отправить заявку"],
            ),
            gold_uc(
                "Назначить ремонт",
                "Диспетчер",
                [3],
                ["просмотреть заявку", "назначить исполнителя и срок"],
            ),
            gold_uc(
                "Завершить ремонт",
                "Исполнитель",
                [4, 5],
                ["обновить статус", "прикрепить результат", "запросить подтверждение жителя"],
                branches=[
                    branch("житель не подтверждает", "переоткрыть заявку", "сохранить комментарий")
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Insurance claim intake",
        language="en",
        complexity="medium",
        task="Create an insurance claim intake and triage workflow.",
        project_name="Claim Intake",
        goal="Collect complete loss reports and route them for review.",
        description="A policyholder reports a loss, uploads evidence, and receives a case number; an adjuster triages it.",
        frs=[
            "A policyholder identifies an active policy.",
            "The policyholder reports loss date, location, and description.",
            "The policyholder uploads supporting evidence.",
            "The system creates a claim number for a complete report.",
            "An adjuster assigns a severity and review route.",
            "The policyholder views claim status.",
        ],
        nfrs=[
            "Uploaded evidence must be malware-scanned.",
            "Sensitive claim data must be encrypted in transit and at rest.",
        ],
        actors={"Policyholder": ["claimant"], "Adjuster": ["claims specialist"]},
        use_cases=[
            gold_uc(
                "Report insurance claim",
                "Policyholder",
                [1, 2, 3, 4],
                [
                    "identify policy",
                    "enter loss details",
                    "upload evidence",
                    "validate completeness",
                    "create claim number",
                ],
                branches=[
                    branch("policy is inactive", "do not create claim", "show policy problem")
                ],
            ),
            gold_uc(
                "Triage insurance claim",
                "Adjuster",
                [5],
                ["review claim", "assign severity", "select review route"],
            ),
            gold_uc(
                "View claim status", "Policyholder", [6], ["identify claim", "show current status"]
            ),
        ],
    ),
    benchmark_case(
        title="Microloan application",
        language="en",
        complexity="hard",
        task="Build a microloan application and decision workflow.",
        project_name="MicroLoan",
        goal="Produce explainable preliminary lending decisions.",
        description="An applicant submits identity, income, and consent; automated checks and an officer produce a decision.",
        frs=[
            "An applicant submits identity and contact information.",
            "The applicant submits income and requested loan data.",
            "The applicant grants consent for credit checks.",
            "The system validates identity through an external provider.",
            "The system obtains a credit risk result.",
            "The system flags inconsistent application data.",
            "A loan officer approves, rejects, or requests clarification.",
            "The applicant receives the decision and reasons allowed by policy.",
        ],
        nfrs=[
            "Every automated and human decision must be explainable and auditable.",
            "Personal data must be deleted according to the approved retention schedule.",
            "External provider failure must not produce an automatic approval.",
        ],
        actors={
            "Applicant": ["borrower"],
            "Loan officer": ["credit officer"],
            "Identity provider": ["KYC provider"],
            "Credit bureau": ["risk provider"],
        },
        use_cases=[
            gold_uc(
                "Submit loan application",
                "Applicant",
                [1, 2, 3],
                [
                    "enter identity",
                    "enter loan and income data",
                    "grant consent",
                    "submit application",
                ],
            ),
            gold_uc(
                "Perform automated checks",
                "Identity provider",
                [4, 5, 6],
                [
                    "verify identity",
                    "obtain risk result",
                    "detect inconsistencies",
                    "prepare review package",
                ],
                branches=[
                    branch(
                        "external check fails",
                        "mark check unavailable",
                        "do not approve automatically",
                    ),
                    branch("data inconsistent", "flag clarification need"),
                ],
            ),
            gold_uc(
                "Decide loan application",
                "Loan officer",
                [7, 8],
                [
                    "review evidence and flags",
                    "record decision",
                    "record permitted reasons",
                    "notify applicant",
                ],
                branches=[
                    branch(
                        "clarification required",
                        "request clarification",
                        "keep application pending",
                    )
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Экстренная диспетчеризация",
        language="ru",
        complexity="hard",
        task="Создать систему регистрации и диспетчеризации экстренных обращений.",
        project_name="Emergency Dispatch",
        goal="Быстро передавать проверенные обращения доступной бригаде.",
        description="Оператор принимает обращение, определяет место и приоритет, диспетчер назначает бригаду и отслеживает подтверждение.",
        frs=[
            "Оператор фиксирует контакт, место и описание происшествия.",
            "Система предлагает категорию и приоритет, но оператор подтверждает их.",
            "Система проверяет полноту критических данных.",
            "Диспетчер видит доступные бригады и их местоположение.",
            "Диспетчер назначает одну бригаду.",
            "Бригада подтверждает получение назначения.",
            "При отсутствии подтверждения назначение эскалируется.",
            "Все изменения обращения сохраняются в журнале.",
        ],
        nfrs=[
            "Создание карточки обращения должно занимать не более 5 секунд после ввода данных.",
            "Потеря связи не должна приводить к исчезновению принятого обращения.",
            "Рекомендация приоритета не может скрывать решение оператора.",
        ],
        actors={
            "Оператор": ["принимающий вызов"],
            "Диспетчер": ["координатор"],
            "Бригада": ["экипаж"],
        },
        use_cases=[
            gold_uc(
                "Зарегистрировать обращение",
                "Оператор",
                [1, 2, 3, 8],
                [
                    "ввести сведения",
                    "получить рекомендацию",
                    "подтвердить категорию и приоритет",
                    "проверить критические данные",
                    "сохранить обращение",
                ],
            ),
            gold_uc(
                "Назначить бригаду",
                "Диспетчер",
                [4, 5, 6, 7, 8],
                [
                    "просмотреть доступные бригады",
                    "выбрать бригаду",
                    "зафиксировать назначение",
                    "получить подтверждение",
                ],
                branches=[
                    branch(
                        "подтверждение не получено",
                        "эскалировать назначение",
                        "сохранить событие в журнале",
                    )
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Marketplace dispute",
        language="en",
        complexity="hard",
        task="Create a marketplace buyer-seller dispute workflow.",
        project_name="FairTrade Disputes",
        goal="Resolve order disputes with traceable evidence and deadlines.",
        description="A buyer opens a dispute, both parties provide evidence, and a mediator decides or proposes a settlement.",
        frs=[
            "A buyer opens a dispute for an eligible order.",
            "The buyer selects a reason and requested outcome.",
            "The buyer and seller upload evidence before a deadline.",
            "The system notifies each party about new evidence.",
            "A mediator reviews order history and evidence.",
            "A mediator proposes a settlement or records a decision.",
            "Either party accepts a proposed settlement.",
            "The system closes the dispute after decision or mutual settlement.",
        ],
        nfrs=[
            "Evidence must be immutable after the submission deadline.",
            "A mediator must not access disputes with a declared conflict of interest.",
        ],
        actors={"Buyer": ["customer"], "Seller": ["merchant"], "Mediator": ["dispute specialist"]},
        use_cases=[
            gold_uc(
                "Open dispute",
                "Buyer",
                [1, 2],
                ["select eligible order", "choose reason and outcome", "create dispute"],
            ),
            gold_uc(
                "Submit dispute evidence",
                "Buyer",
                [3, 4],
                ["upload evidence", "record submission time", "notify other party"],
                branches=[branch("deadline passed", "reject new evidence")],
            ),
            gold_uc(
                "Resolve dispute",
                "Mediator",
                [5, 6, 7, 8],
                [
                    "check conflict of interest",
                    "review history and evidence",
                    "record proposal or decision",
                    "collect settlement responses",
                    "close dispute",
                ],
                branches=[
                    branch(
                        "conflict of interest declared",
                        "prevent access",
                        "route to another mediator",
                    ),
                    branch("both parties accept settlement", "close as settled"),
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Управление доступом в квартиру",
        language="ru",
        complexity="hard",
        task="Создать сервис временного цифрового доступа в многоквартирный дом.",
        project_name="Smart Access",
        goal="Выдавать контролируемый временный доступ гостям и подрядчикам.",
        description="Житель создаёт доступ, управляющий ограничивает зоны, гость использует код, события аудируются.",
        frs=[
            "Житель создаёт приглашение с интервалом действия.",
            "Житель выбирает гостя или подрядчика.",
            "Система назначает разрешённые зоны по типу приглашения.",
            "Управляющий может дополнительно ограничить зоны подрядчика.",
            "Гость получает одноразовый код.",
            "Контроллер проверяет время, зону и статус кода.",
            "После успешного входа одноразовый код блокируется.",
            "Житель досрочно отзывает приглашение.",
        ],
        nfrs=[
            "События доступа должны быть защищены от изменения.",
            "Недоступность сети не должна разрешать просроченный код.",
            "Код не должен отображаться в обычных логах.",
        ],
        actors={
            "Житель": ["резидент"],
            "Управляющий": ["администратор дома"],
            "Гость": ["посетитель"],
            "Контроллер доступа": ["турникет"],
        },
        use_cases=[
            gold_uc(
                "Выдать временный доступ",
                "Житель",
                [1, 2, 3, 4, 5],
                [
                    "указать интервал и тип гостя",
                    "определить зоны",
                    "применить ограничения",
                    "создать одноразовый код",
                    "передать код гостю",
                ],
            ),
            gold_uc(
                "Использовать временный доступ",
                "Гость",
                [6, 7],
                [
                    "предъявить код",
                    "проверить время зону и статус",
                    "разрешить вход",
                    "заблокировать использованный код",
                ],
                branches=[branch("проверка не пройдена", "отказать во входе", "записать событие")],
            ),
            gold_uc(
                "Отозвать доступ",
                "Житель",
                [8],
                ["выбрать активное приглашение", "отозвать приглашение", "заблокировать код"],
            ),
        ],
    ),
    benchmark_case(
        title="Data export request",
        language="en",
        complexity="hard",
        task="Build a personal data export request workflow.",
        project_name="Privacy Export",
        goal="Fulfil verified export requests within a controlled process.",
        description="A user requests an export, verifies identity, and downloads a time-limited archive assembled from multiple services.",
        frs=[
            "A user requests an export of personal data.",
            "The system requires recent identity verification.",
            "The system collects data from registered source services.",
            "The system records unavailable sources without silently omitting them.",
            "The system creates an encrypted archive.",
            "The system sends a time-limited download notification.",
            "The user downloads the archive after re-authentication.",
            "The archive is deleted after expiry.",
        ],
        nfrs=[
            "The export process must complete within the legal service deadline.",
            "Archive links must be single-user and time-limited.",
            "Audit records must exclude archive content.",
        ],
        actors={
            "User": ["data subject"],
            "Source service": ["data provider"],
            "Privacy operator": ["privacy administrator"],
        },
        use_cases=[
            gold_uc(
                "Request personal data export",
                "User",
                [1, 2],
                ["submit export request", "verify identity", "accept request"],
            ),
            gold_uc(
                "Assemble data export",
                "Source service",
                [3, 4, 5, 6],
                [
                    "collect registered sources",
                    "record source failures",
                    "create encrypted archive",
                    "create expiring link",
                    "notify user",
                ],
                branches=[
                    branch(
                        "source unavailable",
                        "record unavailable source",
                        "continue according to policy",
                    )
                ],
            ),
            gold_uc(
                "Download and expire export",
                "User",
                [7, 8],
                ["re-authenticate", "download archive", "expire link", "delete archive"],
            ),
        ],
    ),
    benchmark_case(
        title="Муниципальное разрешение",
        language="ru",
        complexity="hard",
        task="Создать процесс подачи и рассмотрения заявки на муниципальное разрешение.",
        project_name="City Permit",
        goal="Сделать состояние заявки и причины решений прозрачными заявителю.",
        description="Заявитель подаёт документы, система проверяет комплектность, инспектор запрашивает уточнения и принимает решение.",
        frs=[
            "Заявитель выбирает тип разрешения.",
            "Заявитель заполняет обязательные поля и прикладывает документы.",
            "Система проверяет комплектность по типу разрешения.",
            "Система рассчитывает и принимает обязательную пошлину.",
            "Инспектор запрашивает уточнение с указанием недостающих данных.",
            "Заявитель дополняет заявку до срока.",
            "Инспектор одобряет или отклоняет заявку с причиной.",
            "Заявитель скачивает выданное разрешение.",
        ],
        nfrs=[
            "Каждая версия документов должна сохраняться в истории дела.",
            "Решение должно иметь квалифицированную временную метку.",
        ],
        actors={
            "Заявитель": ["гражданин", "организация"],
            "Инспектор": ["муниципальный сотрудник"],
            "Платёжный сервис": ["провайдер оплаты"],
        },
        use_cases=[
            gold_uc(
                "Подать заявку на разрешение",
                "Заявитель",
                [1, 2, 3, 4],
                [
                    "выбрать тип",
                    "заполнить поля",
                    "загрузить документы",
                    "проверить комплектность",
                    "оплатить пошлину",
                    "подать заявку",
                ],
                branches=[
                    branch(
                        "комплект неполный", "не принимать заявку", "показать недостающие данные"
                    ),
                    branch("оплата не подтверждена", "не переводить заявку на рассмотрение"),
                ],
            ),
            gold_uc(
                "Уточнить заявку",
                "Инспектор",
                [5, 6],
                ["сформировать запрос уточнения", "уведомить заявителя", "получить дополнение"],
                branches=[branch("срок уточнения истёк", "закрыть заявку по правилу")],
            ),
            gold_uc(
                "Принять решение",
                "Инспектор",
                [7, 8],
                [
                    "рассмотреть актуальную версию",
                    "зафиксировать решение и причину",
                    "создать разрешение при одобрении",
                    "предоставить результат заявителю",
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Maintenance scheduling with conflict",
        language="en",
        complexity="hard",
        task="Create a preventive maintenance scheduling workflow for factory machines.",
        project_name="MaintPlan",
        goal="Schedule required maintenance without unsafe production overlap.",
        description="Planners create maintenance windows, production approves downtime, technicians execute checklists, and overdue work escalates.",
        frs=[
            "A maintenance planner creates a task from a maintenance rule.",
            "The planner proposes a machine downtime window.",
            "A production manager approves or rejects the downtime window.",
            "The system prevents an approved maintenance window from overlapping an approved production lock.",
            "A technician starts work only after machine isolation is confirmed.",
            "The technician records checklist results and parts used.",
            "A safety officer records release after safety-critical maintenance.",
            "The system escalates overdue maintenance.",
        ],
        nfrs=[
            "The specification also says emergency maintenance may override any production lock without naming an approver.",
            "All safety confirmations must be non-repudiable.",
        ],
        actors={
            "Maintenance planner": ["planner"],
            "Production manager": ["production approver"],
            "Technician": ["maintenance worker"],
            "Safety officer": ["safety approver"],
        },
        use_cases=[
            gold_uc(
                "Schedule maintenance",
                "Maintenance planner",
                [1, 2, 3, 4],
                [
                    "create task",
                    "propose downtime",
                    "obtain production decision",
                    "check overlap",
                    "approve schedule",
                ],
                branches=[
                    branch("production rejects window", "return task for rescheduling"),
                    branch("approved production lock overlaps", "reject maintenance approval"),
                ],
            ),
            gold_uc(
                "Execute maintenance",
                "Technician",
                [5, 6, 7],
                [
                    "confirm machine isolation",
                    "perform checklist",
                    "record results and parts",
                    "obtain safety release",
                ],
                branches=[branch("isolation not confirmed", "block work start")],
            ),
            gold_uc(
                "Escalate overdue maintenance",
                "Maintenance planner",
                [8],
                ["detect overdue task", "notify responsible roles"],
            ),
        ],
        ambiguity="Emergency override names no approving actor and conflicts with overlap prevention; expected status is conflicting/missing information, not an invented approval rule.",
        forbidden_assumptions=[
            "Invent an approver for emergency override",
            "Silently allow emergency override without audit",
        ],
    ),
    benchmark_case(
        title="Appointment triage with missing rule",
        language="en",
        complexity="hard",
        task="Build an online symptom triage and appointment routing service.",
        project_name="Triage Route",
        goal="Route non-emergency requests while identifying cases needing urgent help.",
        description="A patient answers questions; the service gives a routing recommendation and schedules eligible requests.",
        frs=[
            "A patient selects a symptom category.",
            "The patient answers category-specific questions.",
            "The system displays an emergency warning when configured red flags are present.",
            "The system recommends a care route for non-emergency answers.",
            "The patient books an offered appointment.",
            "A clinician reviews submitted answers before the appointment.",
            "The patient can correct answers before clinician review.",
        ],
        nfrs=[
            "The service must state that its output is not a diagnosis.",
            "The requirements do not provide the red-flag rule set.",
            "Sensitive answers must be accessible only to the patient and assigned clinician.",
        ],
        actors={"Patient": ["service user"], "Clinician": ["doctor", "nurse"]},
        use_cases=[
            gold_uc(
                "Complete symptom triage",
                "Patient",
                [1, 2, 3, 4],
                [
                    "select symptom category",
                    "answer questions",
                    "evaluate configured red flags",
                    "show warning or care route",
                ],
                branches=[
                    branch(
                        "configured red flag present",
                        "show emergency warning",
                        "do not present routine booking as sufficient",
                    )
                ],
            ),
            gold_uc(
                "Book routed appointment",
                "Patient",
                [5],
                ["select offered appointment", "confirm booking"],
            ),
            gold_uc(
                "Review triage answers",
                "Clinician",
                [6, 7],
                ["open assigned answers", "review latest submitted version"],
                branches=[
                    branch(
                        "patient corrects before review",
                        "replace current version while preserving audit history",
                    )
                ],
            ),
        ],
        ambiguity="Red-flag rules are missing; generation must expose missing information and must not invent clinical thresholds.",
        forbidden_assumptions=[
            "Invent medical red-flag thresholds",
            "Describe the recommendation as a diagnosis",
        ],
    ),
    benchmark_case(
        title="Fleet charging schedule",
        language="en",
        complexity="hard",
        task="Create an electric fleet charging scheduling workflow.",
        project_name="FleetCharge",
        goal="Prepare vehicles for trips while respecting charger and power limits.",
        description="A dispatcher supplies trip needs; the system proposes charging sessions and operators handle failures.",
        frs=[
            "A dispatcher imports next-day vehicle trip requirements.",
            "The system reads vehicle state of charge.",
            "The system reads charger availability.",
            "The system proposes charging sessions before departure deadlines.",
            "The schedule must not exceed the site power limit.",
            "An operator approves or edits the schedule.",
            "A charger reports session start, progress, completion, or failure.",
            "The system replans remaining sessions after a failure.",
        ],
        nfrs=[
            "Schedule calculation must finish within five minutes for 500 vehicles.",
            "Every manual schedule edit must be attributed to an operator.",
        ],
        actors={
            "Dispatcher": ["fleet planner"],
            "Operator": ["charging operator"],
            "Charger": ["charging station"],
        },
        use_cases=[
            gold_uc(
                "Plan fleet charging",
                "Dispatcher",
                [1, 2, 3, 4, 5, 6],
                [
                    "import trip needs",
                    "read charge states",
                    "read charger availability",
                    "propose sessions",
                    "check power limit",
                    "approve or edit schedule",
                ],
                branches=[
                    branch("proposal exceeds power limit", "adjust sessions before approval")
                ],
            ),
            gold_uc(
                "Monitor and replan charging",
                "Charger",
                [7, 8],
                [
                    "receive session event",
                    "update session state",
                    "replan remaining sessions when needed",
                ],
                branches=[
                    branch(
                        "charging session fails",
                        "mark failure",
                        "replan remaining sessions",
                        "notify operator",
                    )
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Модерация объявления",
        language="ru",
        complexity="hard",
        task="Создать процесс публикации и модерации объявления на площадке.",
        project_name="Safe Listing",
        goal="Публиковать допустимые объявления с прозрачной процедурой обжалования.",
        description="Продавец отправляет объявление, автоматические правила и модератор проверяют его, продавец может исправить или обжаловать решение.",
        frs=[
            "Продавец создаёт черновик объявления с категорией, описанием и ценой.",
            "Продавец загружает изображения.",
            "Система выполняет автоматические проверки запрещённого содержания.",
            "Модератор подтверждает публикацию или отклоняет объявление с причиной.",
            "Продавец исправляет отклонённое объявление и отправляет повторно.",
            "Продавец обжалует решение модератора.",
            "Другой модератор рассматривает апелляцию.",
            "Система сохраняет историю версий и решений.",
        ],
        nfrs=[
            "Модератор апелляции не должен быть автором исходного решения.",
            "Автоматическая проверка не должна единолично публиковать объявление высокой категории риска.",
        ],
        actors={
            "Продавец": ["автор объявления"],
            "Модератор": ["контент-модератор"],
            "Модератор апелляции": ["апелляционный модератор"],
        },
        use_cases=[
            gold_uc(
                "Отправить объявление",
                "Продавец",
                [1, 2, 3],
                [
                    "заполнить объявление",
                    "загрузить изображения",
                    "выполнить автоматические проверки",
                    "отправить на модерацию",
                ],
                branches=[
                    branch(
                        "найдено запрещённое содержание",
                        "зафиксировать флаг",
                        "не публиковать автоматически",
                    )
                ],
            ),
            gold_uc(
                "Модерировать объявление",
                "Модератор",
                [4, 5, 8],
                [
                    "просмотреть актуальную версию и флаги",
                    "зафиксировать решение и причину",
                    "опубликовать или вернуть на исправление",
                ],
            ),
            gold_uc(
                "Обжаловать решение",
                "Продавец",
                [6, 7, 8],
                [
                    "подать апелляцию",
                    "назначить другого модератора",
                    "рассмотреть апелляцию",
                    "зафиксировать итог",
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Research dataset access",
        language="en",
        complexity="hard",
        task="Build a controlled research dataset access request workflow.",
        project_name="Data Access Board",
        goal="Grant time-bounded access only to approved research uses.",
        description="A researcher submits a protocol; data owners and ethics reviewers approve conditions; access is provisioned and revoked.",
        frs=[
            "A researcher submits a protocol, purpose, team, and requested datasets.",
            "The system checks completion of required training.",
            "A data owner reviews dataset-specific conditions.",
            "An ethics reviewer approves or rejects sensitive uses.",
            "The researcher accepts approved conditions.",
            "An administrator provisions time-bounded access.",
            "The system records dataset access events.",
            "The system revokes access at expiry or after approval withdrawal.",
        ],
        nfrs=[
            "Research data must not be copied into workflow logs.",
            "Access decisions and conditions must be retained for seven years.",
        ],
        actors={
            "Researcher": ["principal investigator"],
            "Data owner": ["dataset custodian"],
            "Ethics reviewer": ["IRB reviewer"],
            "Administrator": ["access administrator"],
        },
        use_cases=[
            gold_uc(
                "Request dataset access",
                "Researcher",
                [1, 2],
                [
                    "enter protocol and purpose",
                    "select datasets",
                    "check training",
                    "submit request",
                ],
                branches=[
                    branch("training incomplete", "block submission", "show required training")
                ],
            ),
            gold_uc(
                "Review dataset access",
                "Data owner",
                [3, 4, 5],
                [
                    "review dataset conditions",
                    "obtain ethics decision when required",
                    "record approved conditions",
                    "collect researcher acceptance",
                ],
                branches=[branch("sensitive use rejected", "reject request", "record reason")],
            ),
            gold_uc(
                "Provision and revoke access",
                "Administrator",
                [6, 7, 8],
                [
                    "provision bounded access",
                    "record access events",
                    "revoke at expiry or withdrawal",
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Домашняя доставка лекарств",
        language="ru",
        complexity="hard",
        task="Создать процесс заказа и доставки рецептурных и безрецептурных товаров аптеки.",
        project_name="Pharma Delivery",
        goal="Доставлять допустимые заказы с проверкой рецепта и личности получателя.",
        description="Покупатель формирует корзину, фармацевт проверяет рецепт, курьер подтверждает личность и вручает заказ.",
        frs=[
            "Покупатель добавляет доступные товары в корзину.",
            "Система определяет товары, требующие рецепта.",
            "Покупатель загружает рецепт для рецептурного товара.",
            "Фармацевт подтверждает или отклоняет рецепт.",
            "Покупатель выбирает интервал доставки и оплачивает допустимый заказ.",
            "Курьер получает только необходимые данные доставки.",
            "Курьер проверяет личность получателя для рецептурного заказа.",
            "Система фиксирует вручение или неуспешную попытку.",
        ],
        nfrs=[
            "Медицинские сведения не должны быть доступны курьеру.",
            "Заказ с неподтверждённым рецептом нельзя передать в доставку.",
            "Платёжный callback должен обрабатываться идемпотентно.",
        ],
        actors={
            "Покупатель": ["клиент аптеки"],
            "Фармацевт": ["проверяющий рецепт"],
            "Курьер": ["доставщик"],
            "Платёжный сервис": ["провайдер оплаты"],
        },
        use_cases=[
            gold_uc(
                "Оформить аптечный заказ",
                "Покупатель",
                [1, 2, 3, 4, 5],
                [
                    "сформировать корзину",
                    "определить необходимость рецепта",
                    "загрузить и проверить рецепт",
                    "выбрать доставку",
                    "оплатить заказ",
                ],
                branches=[
                    branch(
                        "рецепт отклонён",
                        "не допустить оплату рецептурной позиции",
                        "сообщить причину",
                    )
                ],
            ),
            gold_uc(
                "Доставить аптечный заказ",
                "Курьер",
                [6, 7, 8],
                [
                    "получить минимальные данные доставки",
                    "проверить личность при необходимости",
                    "зафиксировать вручение",
                ],
                branches=[
                    branch(
                        "личность не подтверждена",
                        "не вручать рецептурный заказ",
                        "зафиксировать неуспешную попытку",
                    )
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Conference paper review assignment",
        language="en",
        complexity="hard",
        task="Create a conference paper reviewer assignment workflow.",
        project_name="ReviewAssign",
        goal="Assign qualified reviewers while avoiding conflicts of interest.",
        description="Authors submit papers; reviewers declare expertise and conflicts; chairs create and adjust assignments.",
        frs=[
            "An author submits a paper with topics and author affiliations.",
            "A reviewer declares topic expertise.",
            "A reviewer declares conflicts of interest.",
            "The system proposes reviewers based on expertise and load.",
            "The system excludes declared and institutional conflicts.",
            "A program chair approves or edits assignments.",
            "A reviewer accepts or declines an assignment.",
            "The chair replaces a declined reviewer.",
        ],
        nfrs=[
            "Reviewer identity must not be disclosed to authors.",
            "Every manual conflict override requires a recorded justification.",
        ],
        actors={"Author": ["paper author"], "Reviewer": ["referee"], "Program chair": ["chair"]},
        use_cases=[
            gold_uc(
                "Submit paper",
                "Author",
                [1],
                ["enter paper metadata", "record topics and affiliations", "submit paper"],
            ),
            gold_uc(
                "Declare reviewer profile",
                "Reviewer",
                [2, 3],
                ["record expertise", "record conflicts"],
            ),
            gold_uc(
                "Assign reviewers",
                "Program chair",
                [4, 5, 6, 7, 8],
                [
                    "generate candidates",
                    "exclude conflicts",
                    "balance load",
                    "approve assignments",
                    "collect responses",
                    "replace declines",
                ],
                branches=[
                    branch("reviewer declines", "remove assignment", "select replacement"),
                    branch(
                        "manual conflict override", "require justification", "record audit event"
                    ),
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Складской инцидент",
        language="ru",
        complexity="hard",
        task="Создать процесс регистрации и расследования инцидента на складе.",
        project_name="Incident Review",
        goal="Сохранять доказательства и контролировать корректирующие действия.",
        description="Сотрудник сообщает инцидент, руководитель изолирует зону, специалист расследует причины и назначает действия.",
        frs=[
            "Сотрудник регистрирует время, место и описание инцидента.",
            "Сотрудник прикладывает доступные материалы.",
            "Руководитель смены классифицирует немедленный риск.",
            "При высоком риске руководитель изолирует зону.",
            "Специалист по безопасности назначается расследователем.",
            "Расследователь фиксирует причины и доказательства.",
            "Расследователь создаёт корректирующие действия с ответственными и сроками.",
            "Руководитель закрывает инцидент после проверки выполнения действий.",
        ],
        nfrs=[
            "Исходные доказательства нельзя изменять после загрузки.",
            "Доступ к персональным данным свидетелей должен быть ограничен.",
        ],
        actors={
            "Сотрудник": ["заявитель"],
            "Руководитель смены": ["начальник смены"],
            "Расследователь": ["специалист по безопасности"],
        },
        use_cases=[
            gold_uc(
                "Зарегистрировать инцидент",
                "Сотрудник",
                [1, 2],
                ["указать обстоятельства", "прикрепить материалы", "создать инцидент"],
            ),
            gold_uc(
                "Ограничить немедленный риск",
                "Руководитель смены",
                [3, 4],
                ["классифицировать риск", "зафиксировать защитное действие"],
                branches=[branch("риск высокий", "изолировать зону")],
            ),
            gold_uc(
                "Расследовать и закрыть инцидент",
                "Расследователь",
                [5, 6, 7, 8],
                [
                    "назначить расследователя",
                    "зафиксировать причины и доказательства",
                    "создать корректирующие действия",
                    "проверить выполнение",
                    "закрыть инцидент",
                ],
            ),
        ],
    ),
    benchmark_case(
        title="Catering order with substitutions",
        language="en",
        complexity="hard",
        task="Create a corporate catering order workflow.",
        project_name="Office Catering",
        goal="Confirm feasible catering orders with dietary constraints.",
        description="An organizer orders menus for attendees; the caterer confirms availability and proposes substitutions.",
        frs=[
            "An organizer enters event time, location, and attendee count.",
            "The organizer records dietary restrictions by count without attendee names.",
            "The organizer selects menu items and quantities.",
            "The system checks ordering cutoff and minimum quantities.",
            "The caterer confirms availability or proposes substitutions.",
            "The organizer accepts or rejects each substitution.",
            "The system calculates the final price.",
            "The organizer approves the final order.",
        ],
        nfrs=[
            "Dietary information must not identify individual attendees.",
            "Price changes after approval require a new explicit approval.",
        ],
        actors={"Organizer": ["event organizer"], "Caterer": ["supplier"]},
        use_cases=[
            gold_uc(
                "Create catering order",
                "Organizer",
                [1, 2, 3, 4],
                [
                    "enter event details",
                    "record aggregate restrictions",
                    "select menu and quantities",
                    "check cutoff and minimums",
                    "submit order",
                ],
                branches=[
                    branch("cutoff or minimum rule fails", "block submission", "show violated rule")
                ],
            ),
            gold_uc(
                "Resolve menu availability",
                "Caterer",
                [5, 6],
                ["check availability", "propose substitutions", "collect organizer decisions"],
            ),
            gold_uc(
                "Approve final catering order",
                "Organizer",
                [7, 8],
                ["calculate final price", "review final contents and price", "approve order"],
                branches=[
                    branch(
                        "price changes after approval",
                        "invalidate previous approval",
                        "request new approval",
                    )
                ],
            ),
        ],
    ),
]

# Freeze the public candidate at exactly 30 cases. Six additional hard cases are
# retained below the cut as a documented reserve pool and are not part of v1.0.
CASES = CASE_CANDIDATES[:30]


def _materialize() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(CASES) != 30:
        raise ValueError(f"Expected exactly 30 cases, got {len(CASES)}")

    # Deterministic stratified holdout: both splits contain multiple languages
    # and all three complexity levels. Positions are fixed before any run.
    hidden_positions = {3, 7, 10, 13, 16, 19, 22, 25, 28, 30}
    split_sequence = {"development": 0, "hidden": 0}
    materialized: list[dict[str, Any]] = []
    for idx, item in enumerate(CASES, start=1):
        split = "hidden" if idx in hidden_positions else "development"
        split_sequence[split] += 1
        local_idx = split_sequence[split]
        case_id = f"B1-{'DEV' if split == 'development' else 'HID'}-{local_idx:03d}"
        record = {"case_id": case_id, "split": split, **item}
        for uc_idx, uc in enumerate(record["gold"]["use_case_slots"], start=1):
            uc["slot_id"] = f"GUC-{uc_idx:03d}"
            uc["source_fr_ids"] = [f"FR-{number:03d}" for number in uc.pop("source_fr_numbers")]
        record["gold"]["trace_expectations"] = [
            {
                "source_fr_id": f"FR-{fr_idx:03d}",
                "allowed_target_uc_slots": [
                    uc["slot_id"]
                    for uc in record["gold"]["use_case_slots"]
                    if f"FR-{fr_idx:03d}" in uc["source_fr_ids"]
                ],
            }
            for fr_idx in range(1, len(record["specification_req"]["functional_requirements"]) + 1)
        ]
        materialized.append(record)

    if split_sequence != {"development": 20, "hidden": 10}:
        raise ValueError(f"Unexpected split counts: {split_sequence}")

    cases_json = json.dumps(materialized, ensure_ascii=False, indent=2) + "\n"
    digest = hashlib.sha256(cases_json.encode("utf-8")).hexdigest()
    manifest = {
        "benchmark_version": "1.0.0-synthetic-candidate",
        "created_at": "2026-09-08",
        "frozen": False,
        "freeze_blocker": "Supervisor/expert review and written approval are required.",
        "case_count": len(materialized),
        "reserve_case_count": len(CASE_CANDIDATES) - len(CASES),
        "split_counts": dict(Counter(case["split"] for case in materialized)),
        "complexity_counts": dict(Counter(case["complexity"] for case in materialized)),
        "language_counts": dict(Counter(case["language"] for case in materialized)),
        "cases_sha256": digest,
        "hidden_policy": "Hidden means held out from prompt/threshold tuning. Gold exists locally for final evaluation and is not cryptographically secret from the repository owner.",
        "provenance": "Synthetic cases authored for pipeline development; not supplied or approved by the supervisor.",
        "required_review": [
            "domain plausibility",
            "gold actor and use-case boundaries",
            "milestone and branch completeness",
            "ambiguity/conflict labels",
            "permission to use the set in the final NIR",
        ],
    }
    return materialized, manifest


def main() -> None:
    materialized, manifest = _materialize()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(
        json.dumps(materialized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
