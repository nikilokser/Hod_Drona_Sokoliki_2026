# Патч: таймаут на ROS service call в drone_ros_bridge.py

Патч для стороннего репозитория `dark516/sverk_drone_agent` (не входит в этот
git-репозиторий, живёт на каждом дроне в `~/catkin_ws/src/sverk_drone_agent`).
Уже применён и проверен на `sverk-8` (192.168.1.8) 2026-07-30.

## Что чинит

`rospy.ServiceProxy.__call__()` в ROS1 не имеет таймаута. Если ROS-сервис
(например `land`) не отвечает, вызов в `DroneRos1Bridge._call()` блокируется
навсегда, а так как `call_tool()` держит `self.lock` на всё это время — вообще
любая следующая команда дрону (взлёт, посадка, статус) виснет вместе с ней.
Наружу это выглядит как «дрон не отвечает» и в итоге таймаут-ошибка от
`fleet_text_bridge` (`FLEET_AGENT_COMMAND_TIMEOUT_SEC`, по умолчанию 300 с).

Патч оборачивает вызов сервиса в `ThreadPoolExecutor` с ограничением по
`DRONE_SERVICE_TIMEOUT_SEC` (по умолчанию 5 с) и делает захват `self.lock`
тоже с таймаутом — вместо вечного зависания агент теперь за несколько секунд
вернёт явную ошибку (`timed_out: true`) и освободит очередь для следующей
команды.

Файл, который патчится:
`ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py`

Он используется и «настоящим» LLM-агентом (`drone_agent_mcp_ros1`), и
псевдо-агентом (`drone_pseudo_agent_ros1` импортирует тот же класс
`DroneRos1Bridge`), так что патч актуален для обоих режимов.

**Важно:** это не имеет отношения к найденному отдельно на sverk-8 обрыву
USB между Raspberry Pi и полётным контроллером (Matek H743) — та проблема
физическая (кабель/разъём) и решается только на конкретном железе руками.

## Куда раскатывать

Роботы из `sverk_ai_communication_server/config/fleet.yaml` типа `ros1_drone`:

| robot_id  | IP            | Статус патча       |
|-----------|---------------|---------------------|
| sverk-8   | 192.168.1.8   | применён 2026-07-30 |
| sverk-108 | 192.168.1.108 | применён 2026-07-30 |
| sverk-4   | 192.168.1.4   | не применён         |
| sverk-6   | 192.168.1.6   | не применён         |
| drone-05  | 10.194.179.135| не применён         |
| drone-06  | 10.194.179.136| не применён         |

## Как применить (любой вариант)

Путь на дроне (обычно одинаковый на всех клонах SD-карты, см.
`MULTI_DRONE_SETUP.md`):
```
~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py
```

### Вариант А — git apply / patch (предпочтительно)
```bash
scp 0001-bound-ros-service-call-timeout.patch pi@<IP_ДРОНА>:/home/pi/
ssh pi@<IP_ДРОНА>
cd ~/catkin_ws/src/sverk_drone_agent
git apply --check ~/0001-bound-ros-service-call-timeout.patch   # проверка
git apply ~/0001-bound-ros-service-call-timeout.patch           # либо: patch -p1 < ~/0001-...patch
rm ~/0001-bound-ros-service-call-timeout.patch
```

### Вариант Б — просто перезаписать файл
```bash
scp drone_ros_bridge.py.patched pi@<IP_ДРОНА>:~/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_agent_mcp_ros1/src/drone_agent_mcp_ros1/drone_ros_bridge.py
```
(на всякий случай сделайте бэкап оригинала перед перезаписью:
`cp drone_ros_bridge.py drone_ros_bridge.py.bak-$(date +%Y%m%d-%H%M%S)`)

## После применения — обязательно

Пересборка не нужна (чистый Python, catkin dev-режим подхватывает файл из
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
