Задание 1. Кеширование
Приведите примеры проблем, которые может решить кеширование.

Приведите ответ в свободной форме.

Кеширование повышает производительность системы
Кеширование оптимизирует работу системы за счет, расположения в быстром кеше данных, к которым выполняются запросы чаще всего, а так же экономии ресурсов (обращаемся не к БД а к кешу) и сглаживания бустов трафика во время пиковых нагрузок обращений к БД.

# Задание 2. Memcached
Установите и запустите memcached.

Приведите скриншот systemctl status memcached, где будет видно, что memcached запущен.
# Обновление пакетов
sudo apt update

# Установка Memcached
sudo apt install memcached

# Запуск сервиса
sudo systemctl start memcached
sudo systemctl enable memcached

# Проверка статуса
sudo systemctl status memcached
<img width="954" height="654" alt="image" src="https://github.com/user-attachments/assets/b0e7bf44-679d-4ea5-816d-f28f9756f797" />


# Задание 3. Удаление по TTL в Memcached
Запишите в memcached несколько ключей с любыми именами и значениями, для которых выставлен TTL 5.

Приведите скриншот, на котором видно, что спустя 5 секунд ключи удалились из базы.

<img width="783" height="677" alt="image" src="https://github.com/user-attachments/assets/e895cc8b-e86f-471a-bd31-76a5e30cfab0" />

# Задание 4. Запись данных в Redis
Запишите в Redis несколько ключей с любыми именами и значениями.

Через redis-cli достаньте все записанные ключи и значения из базы, приведите скриншот этой операции.
# Установка и проверка redis
#sudo apt install -y redis
#sudo systemctl status redis


<img width="1310" height="775" alt="image" src="https://github.com/user-attachments/assets/af778919-2cce-4d89-a3a5-b5146dc2d72a" />

# Листинг команд
#redis-cli
#scan 0
#set k1 test
#set k2 100
#scan 0
#get k1
#get k2
#flushall
#exit
<img width="764" height="706" alt="image" src="https://github.com/user-attachments/assets/caf4657f-2131-4e08-a8e1-115efb4412a0" />

