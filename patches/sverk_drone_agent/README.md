# Патчи для sverk_drone_agent

Патчи для стороннего репозитория `dark516/sverk_drone_agent` (не входит в этот
git-репозиторий, живёт на каждом дроне в `~/catkin_ws/src/sverk_drone_agent`).
Применять по порядку: `0001` → `0002` → `0003`. `*.patched` — итоговые файлы
после всех трёх патчей (можно накатить одним копированием вместо применения
диффов).

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

## Голосование по предложенному ходу — конфиг, не патч кода

См. дизайн `docs/superpowers/specs/2026-07-31-ai-move-negotiation-design.md`.
Веб-морда (`move_orchestrator.py`) рассылает предложенный ход агентам фигур с
префиксом `[ГОЛОСОВАНИЕ]` и ждёт ответ в формате `ДА:`/`НЕТ:`/`ХОД: <откуда>-
<куда>:`. Это решается **конфигом**, без изменения кода вендора — через уже
существующий хук `AGENT_PROMPT_FILE` (`agent_text_node.py::system_prompt()`),
текст для дописывания — `agent_prompt_voting_addition.md` рядом с этим файлом.

**Важное условие, которое нужно проверить перед раскаткой на конкретном
дроне: голосование работает только в режиме `agent` (настоящий LLM,
`drone_agent_mcp_ros1`), а не в `pseudo` (`drone_pseudo_agent_ros1`).**
У псевдо-агента нет LLM вообще — `command_parser.py` разбирает текст
регулярками под конкретный список команд полёта, никакой ветки для
свободного текста вроде `[ГОЛОСОВАНИЕ] ...` там нет, ответ будет ошибкой
парсинга. На момент патчей 0001-0003 и `sverk-8`, и `sverk-108` работали
именно в `pseudo`-режиме (`DRONE_AGENT_MODE=pseudo`, видно по
`drone_pseudo_agent_stack.launch` в выводе `systemctl status`) — переключение
на `agent` для голосования ещё не сделано ни на одном дроне.

Шаги для конкретного дрона (не выполнялись автоматически, нужно
подтверждение перед раскаткой на живом железе):

1. Проверить/выставить в systemd override (`/etc/systemd/system/sverk-drone-agent.service.d/override.conf`):
   `DRONE_AGENT_MODE=agent` (сейчас `pseudo`), `OPENAI_BASE_URL=https://ai.sverk.io/v1`,
   `OPENAI_MODEL=<слабая модель, например gemma-4-31b>`, `OPENAI_API_KEY=<ключ шлюза>`.
2. Найти/создать `config/agent_prompt.md` в
   `~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/` и
   **дописать** в конец содержимое `agent_prompt_voting_addition.md`.
3. Убедиться, что `AGENT_PROMPT_FILE` в override указывает на этот файл
   (по умолчанию пусто — кастомизация не подключена, пока явно не задано).
4. `rm -rf .../drone_agent_mcp_ros1/__pycache__` (если есть), `sudo systemctl daemon-reload`,
   `sudo systemctl restart sverk-drone-agent.service`.
5. Проверить тем же способом, что и после патчей 0001-0003 (см. «Быстрая
   проверка после рестарта» ниже) плюс отдельно голосовым сообщением
   вручную через `rostopic pub` с текстом `[ГОЛОСОВАНИЕ] ...` — ожидается
   ответ строго `ДА:`/`НЕТ:`/`ХОД: ...`, без вызова инструментов полёта.

Переключение в `agent`-режим меняет и обычные полётные команды: они тоже
пойдут через реальный LLM вместо детерминированного `command_parser`, так что
это не изолированное изменение только для голосования — стоит перепроверить
обычный сценарий взлёт/перелёт/посадка после переключения, а не только
голосование.

## Куда раскатывать

Роботы из `sverk_ai_communication_server/config/fleet.yaml` типа `ros1_drone`:

| robot_id  | IP            | 0001                | 0002                | 0003                |
|-----------|---------------|----------------------|----------------------|----------------------|
| sverk-8   | 192.168.1.8   | применён 2026-07-30  | применён 2026-07-30  | применён 2026-07-30  |
| sverk-108 | 192.168.1.108 | применён 2026-07-30  | применён 2026-07-30  | применён 2026-07-30  |
| sverk-4   | 192.168.1.4   | не применён          | не применён          | не применён          |
| sverk-6   | 192.168.1.6   | не применён          | не применён          | не применён          |
| drone-05  | 10.194.179.135| не применён          | не применён          | не применён          |
| drone-06  | 10.194.179.136| не применён          | не применён          | не применён          |

## Как применить

Путь на дроне (обычно одинаковый на всех клонах SD-карты, см.
`MULTI_DRONE_SETUP.md`):
```
~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/
```

### Вариант А — git apply / patch (предпочтительно)
```bash
scp 0001-bound-ros-service-call-timeout.patch 0002-separate-service-call-timeout.patch 0003-trust-land-service-success-over-telemetry-poll.patch pi@<IP_ДРОНА>:/home/pi/
ssh pi@<IP_ДРОНА>
cd ~/catkin_ws/src/sverk_drone_agent
git apply --check ~/0001-bound-ros-service-call-timeout.patch && git apply ~/0001-bound-ros-service-call-timeout.patch
git apply --check ~/0002-separate-service-call-timeout.patch && git apply ~/0002-separate-service-call-timeout.patch
git apply --check ~/0003-trust-land-service-success-over-telemetry-poll.patch && git apply ~/0003-trust-land-service-success-over-telemetry-poll.patch
rm ~/0001-bound-ros-service-call-timeout.patch ~/0002-separate-service-call-timeout.patch ~/0003-trust-land-service-success-over-telemetry-poll.patch
```
(на новом, ещё не патченном дроне применяйте все три по порядку; если часть
уже стоит — только оставшиеся. `git apply --check` перед реальным применением
бесплатно скажет, если что-то не сойдётся.)

### Вариант Б — просто перезаписать файлы итоговым состоянием
```bash
scp drone_ros_bridge.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py
scp safety.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/safety.py
```
(на всякий случай сделайте бэкап оригиналов перед перезаписью:
`cp drone_ros_bridge.py drone_ros_bridge.py.bak-$(date +%Y%m%d-%H%M%S)` и то же для `safety.py`)

## После применения — обязательно

Пересборка не нужна (чистый Python, catkin dev-режим подхватывает файлы из
`src/` напрямую), но нужно сбросить кэш байткода и перезапустить процесс:

```bash
rm -rf ~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/__pycache__
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
