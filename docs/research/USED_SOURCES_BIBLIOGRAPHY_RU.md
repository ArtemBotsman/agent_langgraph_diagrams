# Проверенный список использованных источников

Дата проверки метаданных: 16.09.2026.

Нумерация продолжает три источника, уже вынесенные в презентацию: Ferrari et
al. (2024), NOMAD (2025) и Query2Diagram (2026).

## Научные публикации

[4] Bastian Franze, Dominik Fuchß, Friedrich Wattenberg, Till Fuchs, Jan Keim,
Tobias Hey, “Automated Generation of SysML Activity Diagrams from Industrial
Requirements Using LLMs”, IEEE 34th International Requirements Engineering
Conference (RE 2026), Industrial Innovation Papers, 11 pp., 2026. DOI:
10.5445/IR/1000194327.

[5] Mojdeh Rahmanian, Ashkan Sami, Yanchao Yu, “Large Language Models for
Software Engineering Diagrams: A Systematic Review of UML and ER Modelling”,
arXiv preprint arXiv:2607.26100, 2026. DOI: 10.48550/arXiv.2607.26100.

[6] Chunhao Huang, Yuan Yao, Taolue Chen, Xiaoxing Ma, “From Use Cases to
Sequence Diagrams: Schema-Constrained Generation with Large Language Models”,
IEEE 34th International Requirements Engineering Conference (RE 2026),
Research Papers, Montréal, Canada, 2026.

[7] Minxiao Li, Li Zhang, Shuying Yan, Fang Liu, Liehao Li, Yang Liu, Xiaoli
Lian, “Benchmarking Requirement-to-Architecture Generation with Hybrid
Evaluation”, arXiv preprint arXiv:2604.06683, 2026. DOI:
10.48550/arXiv.2604.06683.

[8] Nouf Alturayeif, Irfan Ahmad, Jameleddine Hassine, “TraceLLM: Leveraging
Large Language Models with Prompt Engineering for Enhanced Requirements
Traceability”, Requirements Engineering, vol. 31, article 6, 2026. DOI:
10.1007/s00766-026-00460-1.

[9] Weixing Zhang, Bowen Jiang, Yuhong Fu, Haowei Cheng, Maximilian Hummel,
Vincenzo Scotti, Nathan Hagel, Jialong Li, Georg Grossmann, Markus Stumptner,
Regina Hebig, Daniel Strüber, Anne Koziolek, “Large Language Models in
Model-Driven Engineering: A Systematic Mapping Study”, Empirical Software
Engineering, vol. 32, article 3, 2027; published online 16 July 2026. DOI:
10.1007/s10664-026-10921-4.

[10] Aman Singh Thakur, Kartik Choudhary, Venkat Srinik Ramayapally, Sankaran
Vaidyanathan, Dieuwke Hupkes, “Judging the Judges: Evaluating Alignment and
Vulnerabilities in LLMs-as-Judges”, Proceedings of the Fourth Workshop on
Generation, Evaluation and Metrics (GEM²), pp. 404–430, 2025.

[11] Lin Shi, Chiyu Ma, Wenhua Liang, Xingjian Diao, Weicheng Ma, Soroush
Vosoughi, “Judging the Judges: A Systematic Study of Position Bias in
LLM-as-a-Judge”, Proceedings of IJCNLP-AACL 2025, pp. 292–314, 2025. DOI:
10.18653/v1/2025.ijcnlp-long.18.

[12] Marco Calamo, Massimo Mecella, Monique Snoeck, “Assessing the Suitability
of Large Language Models in Generating UML Class Diagrams as Conceptual
Models”, Enterprise, Business-Process and Information Systems Modeling,
Lecture Notes in Business Information Processing, vol. 558, pp. 211–226,
Springer, 2025. DOI: 10.1007/978-3-031-95397-2_13.

## Стандарты и технические первичные источники

[13] ISO/IEC/IEEE 29148:2018, “Systems and Software Engineering — Life Cycle
Processes — Requirements Engineering”, 2nd ed., ISO, 2018; confirmed in 2024.

[14] Object Management Group, “OMG Unified Modeling Language, Version 2.5.1”,
formal/2017-12-05, December 2017.

[15] LangChain, “LangGraph Documentation: Overview and Persistence”, official
documentation, accessed 16 September 2026.

[16] Hugging Face, “AI Agents Course: Unit 0 — Introduction to Agents”, online
course, accessed 16 September 2026.

[17] Mermaid, “Flowcharts Syntax”, official Mermaid documentation, accessed
16 September 2026.

[18] Pylint, “Pyreverse”, official Pylint documentation, accessed 16 September
2026.

## Дополнительный источник для обоснования метрик диаграмм

[19] Chumeng Liang, Jiaxuan You, “Evaluating LLM-Generated Diagrams as Graphs”,
Proceedings of the 2025 Conference on Empirical Methods in Natural Language
Processing (EMNLP 2025), pp. 12678–12690, 2025. DOI:
10.18653/v1/2025.emnlp-main.640.

Источник [19] добавлен при итоговой проверке литературы. Он напрямую
обосновывает представление диаграммы как графа и раздельную оценку узлов и
путей, но не является доказательством качества именно UML Activity Diagram.

## Роль источников в проекте

- [4], [6] — преобразование требований и Use Cases в поведенческие диаграммы.
- [5], [9] — состояние области, ограничения, воспроизводимость и необходимость
  benchmark с несколькими метриками.
- [7] — гибридная оценка синтаксиса, структуры, содержания и трассировки.
- [8] — Precision, Recall и F-мера для связей требований с артефактами.
- [10], [11] — почему LLM-судья не заменяет Gold-разметку и экспертов.
- [12] — воспроизводимая схема сравнения моделей и prompt-режимов на UML.
- [13], [14] — требования к инженерии требований и семантика UML.
- [15]–[18] — реализация графа, обучение основам агентных систем, рендеринг и
  смежный статический baseline.
- [19] — дополнительное обоснование графовых метрик элементов и путей.

## Исправления относительно старых черновиков

- Правильная ссылка на стандарт — `ISO/IEC/IEEE 29148:2018`; в 2024 году эта
  редакция была подтверждена, но новой редакцией 2024 не стала.
- Правильное название arXiv:2607.26100 — “Large Language Models for Software
  Engineering Diagrams: A Systematic Review of UML and ER Modelling”.
- Запись “A Framework for Evaluating LLM-Generated Sequence Diagrams” с IEEE
  document 11121690 не включена: точное соответствие названия и записи
  издателя независимо не подтверждено.
