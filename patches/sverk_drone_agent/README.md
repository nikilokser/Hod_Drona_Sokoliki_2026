# Патчи для sverk_drone_agent

Патчи для стороннего репозитория `dark516/sverk_drone_agent` (не входит в этот
git-репозиторий, живёт на каждом дроне в `~/catkin_ws/src/sverk_drone_agent`).
Применять по порядку: `0001` → `0002` → `0003` → `0004`. `*.patched` —
итоговые файлы после соответствующих патчей (можно накатить одним
копированием вместо применения диффов).

**Раскатка 0004 (голосование) на остальные дроны — пошаговая инструкция:**
[`DEPLOY_0004.md`](DEPLOY_0004.md).

**Сеть:** третий октет IP дронов сменился на `.12` (например бывший sverk-8
теперь `192.168.12.8`, было `192.168.1.8`) - см. таблицу «Куда раскатывать»
ниже, актуально только для этого дрона (проверено 2026-08-01), для остальных -
уточнить перед подключением.

**Переименование:** `robot_id` бывшего `sverk-8` в `fleet.yaml` сменился на
`king-8` (Gateway требует `robot_id` строго из строчных букв/цифр/дефиса,
подчёркивания запрещены - `king_8` валит контейнер `robot-gateway` в
краш-луп). Физически тот же дрон, тот же IP `192.168.12.8`.

## 0001 — таймаут на ROS service call

`rospy.ServiceProxy.__call__()` в ROS1 не имеет таймаута. Если ROS-сервис
(например `land`) не отвечает, вызов в `DroneRos1Bridge._call()` блокируется
навсегда, а так как `call_tool()` держит `self.lock` на всё это время — вообще
любая следующая команда дрону (взлёт, посадка, статус) виснет вместе с ней.
Наружу это выглядит как «дрон не отвечает» и в итоге таймаут-ошибка от
`fleet_text_bridge` (`FLEET_AGENT_COMMAND_TIMEOUT_SEC`, по умолчанию 300 с).

Патч оборачивает вызов сервиса в `ThreadPoolExecutor` и делает захват
`self.lock` тоже с таймаутом — вместо вечного зависания агент возвращает явную
ошибку (`timed_out: true`) и освобождает очередь для следующей команды.

Файл: `ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py`

## 0002 — отдельный, более щедрый таймаут для самого вызова

0001 по ошибке использовал `DRONE_SERVICE_TIMEOUT_SEC` (5 с) как таймаут и для
проверки «сервис зарегистрирован» (`rospy.wait_for_service`, реально быстро),
и для ожидания ответа самого вызова. На реальном железе `land` объективно
отвечает дольше 5 с под лётной нагрузкой — это подтвердилось на sverk-108
30.07.2026: после 0001 навигация в клетку отрабатывала штатно (взлёт,
перелёт, стабилизация — всё success), а посадка каждый раз обрывалась по
`"ROS service land did not respond within 5.0s"`.

0002 разводит эти два таймаута: `DRONE_SERVICE_TIMEOUT_SEC` (5 с, как раньше)
остаётся только для проверки доступности сервиса, а новый
`DRONE_SERVICE_CALL_TIMEOUT_S` (по умолчанию 20 с) — для ожидания ответа
вызова. Если 20 с всё ещё мало для `land` на конкретном дроне — можно поднять
через env, пересборка/новый патч не нужны.

Файлы:
`ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py`,
`ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/safety.py`

Оба файла используются и «настоящим» LLM-агентом (`drone_agent_mcp_ros1`), и
псевдо-агентом (`drone_pseudo_agent_ros1` импортирует тот же класс
`DroneRos1Bridge`), так что патчи актуальны для обоих режимов.

**Важно:** отдельно на sverk-8 обнаружен обрыв USB между Raspberry Pi и
полётным контроллером (Matek H743) — это физическая проблема
(кабель/разъём/питание), эти патчи её не чинят, чинить можно только руками на
конкретном дроне.

## 0003 — не превращать успешную посадку в ошибку

После 0001+0002 навигация в клетку стала отрабатывать чисто, но посадка почти
всегда возвращалась ошибкой `"Landing command sent, but disarm was not
observed before timeout"`, хотя дрон физически садился и разоружался
нормально. Причина: `drone_land(wait_until_disarmed=True)` (дефолт у
псевдо-агента) после успешного ответа сервиса `land` (на sverk-108 сам ответ
содержал `"message": "Landed and disarmed"` — то есть сервис уже блокируется
до реального приземления и разоружения) ещё до 60 с дополнительно опрашивал
`drone_get_telemetry` в ожидании `armed == False`, и если телеметрия не
успевала это подтвердить (наблюдалось: не подтверждала вообще, хотя посадка
уже состоялась) — код **перезаписывал успех в `success: False`**.

0003 убирает эту перезапись: если сам вызов `land` вернул успех, это и есть
финальный результат; неудачное вторичное подтверждение через телеметрию
только помечается полями `disarmed: false` /
`disarm_confirmation: "..."` для диагностики, но больше не превращает
состоявшуюся посадку в ошибку агента. Заодно дефолтный `timeout_s` для этого
опроса снижен с 60 до 15 с — раз это теперь не блокирует успех, незачем и
ждать так долго.

Файл: `ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py`

## 0004 — голосование по предложенному ходу без переключения в agent-режим

См. дизайн `docs/superpowers/specs/2026-07-31-ai-move-negotiation-design.md`.
Веб-морда (`move_orchestrator.py`) рассылает предложенный ход агентам фигур с
префиксом `[ГОЛОСОВАНИЕ]` и ждёт ответ в формате `ДА:`/`НЕТ:`/`ХОД: <откуда>-
<куда>:`.

**Изначальный план был решить это конфигом** (переключить
`DRONE_AGENT_MODE=pseudo` → `agent` + дописать `agent_prompt_voting_addition.md`
в `config/agent_prompt.md`, см. ниже «Альтернатива»), но у него был существенный
недостаток: `agent`-режим пропускает через реальный LLM **вообще все**
команды, включая обычные полётные (`command_parser.py` в `pseudo` — просто
надёжные регулярки под фиксированный список команд, без LLM вообще, и это
сознательно не трогалось раньше — см. `CLAUDE.md`, «Лимиты безопасности в
коде... трогать не будем»). Переключение всего дрона в `agent` ради одного
голосования означало бы отдать и взлёт/перелёт/посадку на волю LLM.

0004 вместо этого патчит `pseudo_agent_text_node.py` напрямую: сообщение с
префиксом `[ГОЛОСОВАНИЕ]` перехватывается **до** вызова `parse_text_command`,
а всё остальное (обычные команды полёта) продолжает идти через прежний,
проверенный `command_parser.py` без единого изменения.

**Важный нюанс, обнаруженный только на реальном дроне 2026-08-01, не на
`localhost`:** сам HTTP-вызов к LLM **нельзя** делать внутри процесса
rospy-агента — один и тот же запрос (тот же ключ, та же модель, те же
заголовки) стабильно и воспроизводимо срабатывал при запуске как отдельный
процесс (`curl`/чистый `python3`-скрипт, ~0.15-4с), но заметно чаще падал
изнутри `pseudo_agent_text_node.py` (`LLM HTTP 403: Access denied by security
policy`, таймауты) - воспроизвелось даже под чистую сеть (0% потерь пинга) и
на «голом» тесте `rospy.init_node()` + `urllib` без остального кода патча.
Точный механизм не локализован (подозрение на то, как rospy обращается с
сигналами/сокетами, либо на WAF `ai.sverk.io`), но раз стабильно
воспроизводится разница «отдельный процесс = ОК, внутри rospy-агента =
ненадёжно» - решение простое: вызов реально живёт в отдельном скрипте
`vote_llm_call.py`, который `execute_vote()` запускает как **свежий
подпроцесс** (`subprocess.run`) на каждую попытку, а не вызывает in-process.
Подпроцесс не видит ни rospy, ни MCP/tools вообще — из него физически нельзя
управлять дроном, только текстовый ответ или ошибка.

Бюджет по времени согласован с веб-мордой: `move_orchestrator.py` ждёт ответ
робота `VOTE_ANSWER_TIMEOUT_SEC` (60 с, было 30 с - поднято тем же коммитом,
30 с срезало реальный, но чуть медленный ответ до `no_response`). На дроне
`VOTE_MAX_ATTEMPTS=3`, `VOTE_SUBPROCESS_TIMEOUT_SEC=13`,
`VOTE_RETRY_DELAY_SEC=1` - худший случай ~41 с, укладывается с запасом.

Файлы:
`ros1_ws/src/drone_pseudo_agent_ros1/scripts/pseudo_agent_text_node.py`,
`ros1_ws/src/drone_pseudo_agent_ros1/scripts/vote_llm_call.py` (новый).

**Применено на sverk-8 (сейчас `king-8`, см. таблицу ниже) 2026-08-01,
проверено:**
- обычная команда `статус` по-прежнему обрабатывается штатным парсером,
  без изменений в поведении, и до, и после переезда вызова в подпроцесс;
- прямой ROS-тест `[ГОЛОСОВАНИЕ] ...` (после того как задан реальный
  `OPENAI_API_KEY`) — реальный, осмысленный ответ модели вида
  `ДА: <причина>`/`НЕТ: <причина>` вместо ошибки;
- **полный боевой путь**: реальный раунд через веб-морду
  (`POST /api/orchestrator/propose-move` → Gateway → дрон → обратно) —
  `king-8` дал реальный голос (`{"kind":"yes","reason":"e2-e4 — классический
  ход..."}`), событие видно в «Ленте переговоров» веб-морды.

`agent_prompt_voting_addition.md` в этой папке для 0004 **не используется** -
он был написан под план с полным `agent`-режимом (системный промпт целого
агента), в 0004 системный промпт для голосования зашит прямо в патч
(`VOTE_SYSTEM_PROMPT`), отдельно от промпта обычных полётных команд.

### Альтернатива (не применялась) — полное переключение в agent-режим

Если голосование всё же нужно через полноценный agent-режим (например чтобы
заодно и обычные команды шли через LLM), шаги те же, что были здесь описаны
изначально:

1. В systemd override (`/etc/systemd/system/sverk-drone-agent.service.d/override.conf`):
   `DRONE_AGENT_MODE=agent`, `OPENAI_BASE_URL=https://ai.sverk.io/v1`,
   `OPENAI_MODEL=<модель>`, `OPENAI_API_KEY=<ключ шлюза>`.
2. Создать `config/agent_prompt.md` в
   `~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/` и
   дописать в конец содержимое `agent_prompt_voting_addition.md`.
3. `AGENT_PROMPT_FILE` в override указать на этот файл.
4. Сбросить `__pycache__`, `daemon-reload`, `restart`.

Переключение в `agent`-режим меняет и обычные полётные команды — стоит
перепроверить взлёт/перелёт/посадку после переключения, а не только
голосование. Не применялось ни на одном дроне.

## Куда раскатывать

Роботы из `sverk_ai_communication_server/config/fleet.yaml` типа `ros1_drone`.
IP даны на момент последней проверки конкретного дрона - третий октет
сменился на `.12` (см. предупреждение в начале файла), для роботов без
пометки "проверено 2026-08-01" актуальный IP не подтверждён:

| robot_id  | IP             | 0001                | 0002                | 0003                | 0004                |
|-----------|----------------|----------------------|----------------------|----------------------|----------------------|
| king-8 (был sverk-8) | 192.168.12.8 (проверено 2026-08-01, было 192.168.1.8) | применён 2026-07-30 | применён 2026-07-30 | применён 2026-07-30 | применён 2026-08-01, проверен полным боевым путём |
| sverk-108 | 192.168.1.108  | применён 2026-07-30  | применён 2026-07-30  | применён 2026-07-30  | не применён          |
| sverk-4   | 192.168.1.4    | не применён          | не применён          | не применён          | не применён          |
| sverk-6   | 192.168.1.6    | не применён          | не применён          | не применён          | не применён          |
| drone-05  | 10.194.179.135 | не применён          | не применён          | не применён          | не применён          |
| drone-06  | 10.194.179.136 | не применён          | не применён          | не применён          | не применён          |

## Как применить

Путь на дроне (обычно одинаковый на всех клонах SD-карты, см.
`MULTI_DRONE_SETUP.md`):
```
~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/
```

### Вариант А — git apply / patch (предпочтительно)
```bash
scp 0001-bound-ros-service-call-timeout.patch 0002-separate-service-call-timeout.patch 0003-trust-land-service-success-over-telemetry-poll.patch 0004-route-voting-prefix-to-llm-in-pseudo-mode.patch pi@<IP_ДРОНА>:/home/pi/
ssh pi@<IP_ДРОНА>
cd ~/catkin_ws/src/sverk_drone_agent
git apply --check ~/0001-bound-ros-service-call-timeout.patch && git apply ~/0001-bound-ros-service-call-timeout.patch
git apply --check ~/0002-separate-service-call-timeout.patch && git apply ~/0002-separate-service-call-timeout.patch
git apply --check ~/0003-trust-land-service-success-over-telemetry-poll.patch && git apply ~/0003-trust-land-service-success-over-telemetry-poll.patch
git apply --check ~/0004-route-voting-prefix-to-llm-in-pseudo-mode.patch && git apply ~/0004-route-voting-prefix-to-llm-in-pseudo-mode.patch
rm ~/0001-bound-ros-service-call-timeout.patch ~/0002-separate-service-call-timeout.patch ~/0003-trust-land-service-success-over-telemetry-poll.patch ~/0004-route-voting-prefix-to-llm-in-pseudo-mode.patch
```
(на новом, ещё не патченном дроне применяйте все четыре по порядку; если часть
уже стоит — только оставшиеся. `git apply --check` перед реальным применением
бесплатно скажет, если что-то не сойдётся.)

### Вариант Б — просто перезаписать файлы итоговым состоянием
```bash
scp drone_ros_bridge.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py
scp safety.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/safety.py
scp pseudo_agent_text_node.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/pseudo_agent_text_node.py
```
(на всякий случай сделайте бэкап оригиналов перед перезаписью, например
`cp pseudo_agent_text_node.py pseudo_agent_text_node.py.bak-$(date +%Y%m%d-%H%M%S)`
и аналогично для остальных двух файлов)

## После применения — обязательно

Пересборка не нужна (чистый Python, catkin dev-режим подхватывает файлы из
`src/` напрямую), но нужно сбросить кэш байткода и перезапустить процесс:

```bash
rm -rf ~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/__pycache__ \
       ~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/__pycache__ \
       ~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/src/drone_pseudo_agent_ros1/__pycache__
sudo systemctl daemon-reload
sudo systemctl restart sverk-drone-agent.service
systemctl status sverk-drone-agent.service --no-pager   # оба процесса (bridge_node, *_agent_text_node) должны быть active
```

Дрон в этот момент должен стоять на земле, разоружён (`rosservice call
/get_telemetry "{frame_id: 'map'}"` → `armed: False`) — рестарт обрывает
текущую команду агента.

## Быстрая проверка после рестарта

Безопасный нефлайтовый запрос через ROS (без полёта):
```bash
rostopic pub -1 /agent/text_command std_msgs/String \
  "data: '{\"message_id\": \"<любой-uuid>\", \"robot_id\": \"<robot_id_дрона>\", \"text\": \"статус\"}'"
rostopic echo -n 1 /agent/answer
```
Ожидается `status: completed` в течение пары секунд.

После 0004 - тем же способом, но с `"text": "[ГОЛОСОВАНИЕ] тест"`. Ожидается
НЕ `"Команда не поддерживается..."` (это означало бы, что патч не применился
или `__pycache__` не сброшен), а либо реальный ответ `ДА:`/`НЕТ:`/`ХОД: ...`,
либо (если `OPENAI_API_KEY` пуст) явная `Ошибка агента: LLM API key is not
set` - обе реакции подтверждают, что перехват сработал.
