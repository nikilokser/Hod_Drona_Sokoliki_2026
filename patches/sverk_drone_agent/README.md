# Патчи для sverk_drone_agent

Патчи для стороннего репозитория `dark516/sverk_drone_agent` (не входит в этот
git-репозиторий, живёт на каждом дроне в `~/catkin_ws/src/sverk_drone_agent`).
Применять по порядку: `0001` → `0002`. `*.patched` — итоговые файлы после
обоих патчей (можно накатить одним копированием вместо применения диффов).

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
полётным контроллером (Matek H743) и общая нестабильность полёта — это
физическая проблема (кабель/разъём/питание), эти патчи её не чинят, чинить
можно только руками на конкретном дроне.

## Куда раскатывать

Роботы из `sverk_ai_communication_server/config/fleet.yaml` типа `ros1_drone`:

| robot_id  | IP            | 0001                | 0002                |
|-----------|---------------|----------------------|----------------------|
| sverk-8   | 192.168.1.8   | применён 2026-07-30  | не применён (дрон недоступен по сети с 2026-07-30 ~17:00) |
| sverk-108 | 192.168.1.108 | применён 2026-07-30  | применён 2026-07-30  |
| sverk-4   | 192.168.1.4   | не применён          | не применён          |
| sverk-6   | 192.168.1.6   | не применён          | не применён          |
| drone-05  | 10.194.179.135| не применён          | не применён          |
| drone-06  | 10.194.179.136| не применён          | не применён          |

## Как применить

Путь на дроне (обычно одинаковый на всех клонах SD-карты, см.
`MULTI_DRONE_SETUP.md`):
```
~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/
```

### Вариант А — git apply / patch (предпочтительно)
```bash
scp 0001-bound-ros-service-call-timeout.patch 0002-separate-service-call-timeout.patch pi@<IP_ДРОНА>:/home/pi/
ssh pi@<IP_ДРОНА>
cd ~/catkin_ws/src/sverk_drone_agent
git apply --check ~/0001-bound-ros-service-call-timeout.patch && git apply ~/0001-bound-ros-service-call-timeout.patch
git apply --check ~/0002-separate-service-call-timeout.patch && git apply ~/0002-separate-service-call-timeout.patch
rm ~/0001-bound-ros-service-call-timeout.patch ~/0002-separate-service-call-timeout.patch
```
(на новом, ещё не патченном дроне применяйте оба по порядку; если 0001 уже
стоит — только 0002. `git apply --check` перед реальным применением бесплатно
скажет, если что-то не сойдётся.)

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

## Известное открытое: sverk-8 недоступен

С ~17:00 2026-07-30 `192.168.1.8` не отвечает ни на ping, ни на SSH — не
запушен 0002. Проверить физически (питание/Wi-Fi/не завис ли Pi) и накатить
0002, когда снова будет в сети.
