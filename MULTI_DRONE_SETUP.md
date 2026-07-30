# Настройка нескольких дронов из одного образа SD-карты

Эта инструкция описывает подготовку нескольких дронов, созданных из одного
образа SD-карты SVERK. После прошивки все копии имеют одинаковые системные и
прикладные идентификаторы, поэтому перед одновременным подключением к сети их
необходимо изменить.

## Главные требования

У каждого дрона должны быть уникальными:

- системное имя `hostname`;
- `FLEET_ROBOT_ID`;
- `LLM_APP_TITLE`;
- Linux `machine-id`;
- SSH host keys;
- сетевой IP-адрес или DHCP-резервация.

Особенно важен `FLEET_ROBOT_ID`. MQTT bridge использует идентификатор клиента
вида `bridge-<robot_id>`. Если два дрона подключатся с одинаковым
`FLEET_ROBOT_ID`, брокер будет поочередно отключать их друг от друга.

Пример распределения:

| Дрон | hostname | `FLEET_ROBOT_ID` | `LLM_APP_TITLE` |
|---|---|---|---|
| 1 | `sverk-drone-01` | `drone-01` | `sverk-agent-01` |
| 2 | `sverk-drone-02` | `drone-02` | `sverk-agent-02` |
| 3 | `sverk-drone-03` | `drone-03` | `sverk-agent-03` |

## Общие параметры

Следующие параметры могут быть одинаковыми на всех дронах:

```bash
export FLEET_SERVER_IP='10.63.18.3'
export FLEET_MQTT_HOST="$FLEET_SERVER_IP"
export FLEET_MQTT_PORT='1883'
export FLEET_MQTT_TOPIC_PREFIX='fleet/v1/robots'

export ROS_MASTER_URI='http://127.0.0.1:11311'
unset ROS_IP
unset ROS_HOSTNAME
```

`10.63.18.3` является текущим примером адреса сервера. Для постоянной работы
серверу рекомендуется назначить статический IP или DHCP-резервацию.

Одинаковыми также могут оставаться:

- адрес и модель LLM;
- локальный MCP-порт;
- карта ArUco;
- размер шахматной клетки;
- параметры взлета, полета и посадки;
- ограничения безопасности.

MQTT-логин и пароль технически могут быть общими. Для постоянной эксплуатации
безопаснее создать отдельную учетную запись для каждого дрона и ограничить ее
доступ топиками только этого `robot_id`.

## Порядок подготовки нового дрона

Первый запуск каждой копии выполняйте отдельно. Исходный дрон с тем же образом
лучше временно выключить или отключить от MQTT-сети. Иначе новый клон успеет
подключиться к брокеру с уже используемым `robot_id`.

### 1. Подключение и остановка агента

Подключитесь к дрону по его временному DHCP-адресу:

```bash
ssh pi@<IP_ДРОНА>
```

Остановите автозапущенный агент:

```bash
sudo systemctl stop sverk-drone-agent.service
```

### 2. Изменение hostname

Для второго дрона:

```bash
sudo hostnamectl set-hostname sverk-drone-02
sudo nano /etc/hosts
```

В `/etc/hosts` найдите строку со старым hostname:

```text
127.0.1.1 sverk-51813
```

Замените ее на:

```text
127.0.1.1 sverk-drone-02
```

Для следующих дронов используйте `sverk-drone-03`, `sverk-drone-04` и так
далее.

Wrapper автозапуска формирует `ROS_HOSTNAME` из системного hostname, поэтому
отдельно задавать IP дрона в ROS-конфигурации не требуется.

### 3. Изменение параметров агента

Откройте файл окружения:

```bash
nano ~/.sverk_drone_agent_env.sh
```

Для второго дрона укажите:

```bash
export FLEET_ROBOT_ID='drone-02'
export LLM_APP_TITLE='sverk-agent-02'

export FLEET_SERVER_IP='10.63.18.3'
export FLEET_MQTT_HOST="$FLEET_SERVER_IP"
export FLEET_MQTT_PORT='1883'
export FLEET_MQTT_TOPIC_PREFIX='fleet/v1/robots'

export ROS_MASTER_URI='http://127.0.0.1:11311'
unset ROS_IP
unset ROS_HOSTNAME
```

Остальные параметры полета, карты, LLM и безопасности можно оставить такими
же, как в исходном образе.

Защитите файл с API-ключами и MQTT-паролем:

```bash
chmod 600 ~/.sverk_drone_agent_env.sh
```

### 4. Обновление machine-id

Клонированные системы имеют одинаковый Linux `machine-id`. Это может мешать
корректной DHCP-идентификации и учету устройств.

Создайте новый идентификатор:

```bash
sudo rm -f /etc/machine-id /var/lib/dbus/machine-id
sudo systemd-machine-id-setup
sudo ln -s /etc/machine-id /var/lib/dbus/machine-id
```

### 5. Обновление SSH host keys

Копии образа также содержат одинаковые серверные SSH-ключи. Создайте новые:

```bash
sudo rm -f /etc/ssh/ssh_host_*
sudo ssh-keygen -A
```

После этого сохраненная на компьютере SSH-запись для данного IP может
потребовать удаления:

```bash
ssh-keygen -R <IP_ДРОНА>
```

### 6. Настройка сети

Рекомендуемый вариант:

- оставить дроны в режиме DHCP;
- создать на роутере DHCP-резервацию для каждого аппаратного MAC-адреса;
- назначить каждому дрону предсказуемый адрес.

Пример:

| Дрон | Пример IP |
|---|---|
| `drone-01` | `10.63.18.231` |
| `drone-02` | `10.63.18.232` |
| `drone-03` | `10.63.18.233` |

Адреса в таблице являются примерами. Перед их использованием убедитесь, что
они свободны и входят в подсеть вашей сети.

Если в образе настроен статический IP, его обязательно нужно изменить перед
одновременным включением нескольких копий.

### 7. Выбор типа агента

В текущем образе через systemd запускается псевдоагент:

```ini
[Service]
Environment=DRONE_AGENT_MODE=pseudo
```

Настройка находится в:

```text
/etc/systemd/system/sverk-drone-agent.service.d/override.conf
```

Для обычного LLM-агента замените значение на:

```ini
[Service]
Environment=DRONE_AGENT_MODE=agent
```

Обычному агенту дополнительно необходим корректный `OPENAI_API_KEY`. После
изменения режима выполните:

```bash
sudo systemctl daemon-reload
sudo systemctl restart sverk-drone-agent.service
```

На одном дроне одновременно должен работать только один режим агента.

### 8. Перезагрузка

После завершения настройки:

```bash
sudo reboot
```

Первая загрузка полного ROS-стека может занять около двух минут.

## MQTT-топики

Для каждого `FLEET_ROBOT_ID` bridge использует отдельный набор топиков:

```text
fleet/v1/robots/drone-01/command
fleet/v1/robots/drone-01/answer
fleet/v1/robots/drone-01/status
fleet/v1/robots/drone-01/availability
```

Для второго дрона:

```text
fleet/v1/robots/drone-02/command
fleet/v1/robots/drone-02/answer
fleet/v1/robots/drone-02/status
fleet/v1/robots/drone-02/availability
```

Bridge публикует `availability` с признаком `online`, поэтому сервер,
подписанный на `fleet/v1/robots/#`, может видеть подключившиеся дроны
автоматически. Если на MQTT-брокере включен ACL, необходимо разрешить топики
каждого нового `robot_id`.

## Проверка на дроне

После загрузки выполните:

```bash
hostname
cat /etc/machine-id
grep -E 'FLEET_ROBOT_ID|FLEET_SERVER_IP|FLEET_MQTT_HOST' \
  ~/.sverk_drone_agent_env.sh
```

Проверьте службы:

```bash
systemctl is-active roscore.service
systemctl is-active sverk.service
systemctl is-enabled sverk-drone-agent.service
systemctl status sverk-drone-agent.service --no-pager
```

Проверьте ROS-узлы:

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
rosnode list | grep -E 'fleet_text_bridge|drone_agent|pseudo_agent|aruco_map'
```

Проверьте соединение с MQTT:

```bash
nc -vz "$FLEET_MQTT_HOST" "$FLEET_MQTT_PORT"
ss -ntp | grep ':1883'
```

Проверьте состояние полетного контроллера:

```bash
rostopic echo -n 1 /mavros/state
```

Перед первым тестом значение `armed` должно быть `False`.

Безопасная локальная проверка псевдоагента без запуска моторов:

```bash
rostopic pub -1 /agent/text_command std_msgs/String "data: 'статус'"
rostopic echo -n 1 /agent/answer
```

## Проверка на сервере

Проверьте каждый дрон через API:

```bash
curl http://127.0.0.1:8080/api/v1/robots/drone-01
curl http://127.0.0.1:8080/api/v1/robots/drone-02
curl http://127.0.0.1:8080/api/v1/robots/drone-03
```

Для диагностики всех MQTT-сообщений:

```bash
docker exec -it robot-mosquitto \
  mosquitto_sub -t 'fleet/v1/robots/#' -v
```

В web-чате обращайтесь к конкретному дрону его серверным именем, например:

```text
@drone_01 статус
@drone_02 статус
@drone_03 статус
```

Фактический формат упоминания зависит от интерфейса сервера. В MQTT и ROS
всегда используется точное значение `FLEET_ROBOT_ID`, например `drone-02`.

## Карта ArUco и параметры полета

Все дроны могут использовать одну карту:

```text
/home/pi/catkin_ws/src/sverk/aruco_pose/map/chess_8x8_main.txt
```

Общими могут оставаться:

```bash
export CHESS_MAP_FRAME_ID='aruco_map'
export CHESS_CELL_SIZE_M='0.40'
export CHESS_ARRIVAL_TOLERANCE_M='0.20'
```

Если камеры или их крепления отличаются, для каждого дрона может
потребоваться отдельная калибровка камеры и проверка смещения относительно
центра корпуса.

## Ограничения безопасности

Текущие ROS-пакеты разделяют команды по `robot_id`, но не реализуют:

- предотвращение столкновений между дронами;
- резервирование клеток шахматного поля;
- автоматическую проверку пересечения маршрутов;
- общую диспетчеризацию воздушного пространства.

До появления такой координации не отправляйте нескольким дронам одновременно
пересекающиеся маршруты. Первые испытания каждого клона проводите отдельно,
с оператором и возможностью немедленно остановить полет.

## Краткий чек-лист

- [ ] Уникальный hostname.
- [ ] Уникальный `FLEET_ROBOT_ID`.
- [ ] Уникальный `LLM_APP_TITLE`.
- [ ] Новый `/etc/machine-id`.
- [ ] Новые SSH host keys.
- [ ] Уникальный IP или DHCP-резервация.
- [ ] Правильный IP MQTT-сервера.
- [ ] Выбран режим `pseudo` или `agent`.
- [ ] Служба автозапуска активна.
- [ ] MQTT-соединение установлено.
- [ ] Сервер видит дрон как отдельное устройство.
- [ ] Полетный контроллер подключен и разоружен перед тестом.
- [ ] Первый полет выполнен отдельно от остальных дронов.
